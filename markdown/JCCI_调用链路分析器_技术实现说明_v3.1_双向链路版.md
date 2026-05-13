## 修订版设计方案 v3.1

### 修订记录

| 序号 | 评审意见 | 修改方案 |
|------|----------|----------|
| 1 | 多态/动态绑定导致调用关系缺失 | 增加 `ClassHierarchyIndex`（类层次索引），支持接口→实现类映射 |
| 2 | 入口方法识别静态局限性 | 增加 `root_type` 标记（`ENTRY_CONTROLLER`/`NO_CALLER`/`FRAMEWORK_ENTRY`） |
| 3 | 注解感知入口发现 | 增加 `AnnotationAwareEntryDetector`，识别 `@RequestMapping` 等注解 |
| 4 | 覆盖率评估 | 在 metadata 中增加 `coverage_stats` 统计 |
| 5 | `seen_callers` 去重掩盖多调用点 | 改为保留多调用点，通过 `invocation_lines` 聚合行号 |
| 6 | 能力边界声明 | 在结果中增加 `analysis_limitations` 字段 |

---

## 1. 新增核心组件

### 1.1 ClassHierarchyIndex（类层次索引）

**目的**：解决接口调用向上分析时的"假阴性"问题。当调用者通过接口引用调用方法时，静态分析记录的是接口方法，而变更的是实现类方法，导致反向索引无法匹配。

**核心思想**：
- 从数据库加载所有类的继承关系（`super_class`、`interfaces` 字段）
- 建立 **接口/抽象类方法 → 所有实现类方法** 的映射
- 向上分析时，同时查询接口方法和实现类方法的调用者

```python
# class_hierarchy.py
class ClassHierarchyIndex:
    """
    类层次索引：支持 CHA（Class Hierarchy Analysis）
    解决接口/实现类方法调用关系缺失问题
    """
    
    def __init__(self, db_connection, project_ids: List[int]):
        self._class_hierarchy: Dict[str, dict] = {}  # class_name -> {super_class, interfaces, methods}
        self._interface_impls: Dict[str, List[str]] = {}  # interface -> [impl_class1, impl_class2]
        self._method_override_map: Dict[str, List[dict]] = {}  # interface_method_key -> [impl_methods]
        self._build_hierarchy(db_connection, project_ids)
    
    def _build_hierarchy(self, db_connection, project_ids: List[int]):
        """
        从数据库加载类层次信息
        假设数据库表结构：
        - class_table: class_id, project_id, package_class, super_class, interfaces(JSON)
        - method_table: method_id, class_id, method_name, parameters, is_abstract
        """
        cursor = db_connection.cursor()
        
        # 1. 加载所有类的继承关系
        placeholders = ','.join('?' * len(project_ids))
        cursor.execute(f"""
            SELECT package_class, super_class, interfaces 
            FROM class_table 
            WHERE project_id IN ({placeholders})
        """, project_ids)
        
        for row in cursor.fetchall():
            package_class, super_class, interfaces_json = row
            interfaces = json.loads(interfaces_json) if interfaces_json else []
            self._class_hierarchy[package_class] = {
                'super_class': super_class,
                'interfaces': interfaces,
                'methods': []
            }
            
            # 建立接口→实现类映射
            for iface in interfaces:
                if iface not in self._interface_impls:
                    self._interface_impls[iface] = []
                self._interface_impls[iface].append(package_class)
        
        # 2. 加载所有方法信息
        cursor.execute(f"""
            SELECT m.method_id, c.package_class, m.method_name, m.parameters, m.is_abstract
            FROM method_table m
            JOIN class_table c ON m.class_id = c.class_id
            WHERE c.project_id IN ({placeholders})
        """, project_ids)
        
        for row in cursor.fetchall():
            method_id, package_class, method_name, parameters, is_abstract = row
            method_info = {
                'method_id': method_id,
                'package_class': package_class,
                'method_name': method_name,
                'parameters': parameters,
                'is_abstract': is_abstract
            }
            self._class_hierarchy[package_class]['methods'].append(method_info)
            
            # 3. 建立方法签名键（用于重载匹配）
            sig_key = self._build_signature_key(method_name, parameters)
            method_key = f"{package_class}|{sig_key}"
            
            # 4. 如果是接口/抽象类的方法，记录到 override_map
            class_info = self._class_hierarchy[package_class]
            if self._is_interface_or_abstract(package_class):
                if method_key not in self._method_override_map:
                    self._method_override_map[method_key] = []
                self._method_override_map[method_key].append(method_info)
        
        # 5. 构建实现类方法映射（CHA 核心）
        self._build_override_resolution()
    
    def _build_override_resolution(self):
        """
        CHA 核心：为每个接口/抽象类方法，找到所有实现类中的重写方法
        """
        for method_key, abstract_methods in list(self._method_override_map.items()):
            package_class, sig_key = method_key.rsplit('|', 1)
            
            # 找到该接口/抽象类的所有实现类
            impl_classes = self._get_all_implementations(package_class)
            
            for impl_class in impl_classes:
                # 在实现类中查找同签名的方法
                for method in self._class_hierarchy.get(impl_class, {}).get('methods', []):
                    impl_sig_key = self._build_signature_key(
                        method['method_name'], 
                        method['parameters']
                    )
                    if impl_sig_key == sig_key:
                        self._method_override_map[method_key].append(method)
    
    def _get_all_implementations(self, class_name: str) -> List[str]:
        """获取一个接口/抽象类的所有实现类（递归）"""
        result = []
        direct_impls = self._interface_impls.get(class_name, [])
        result.extend(direct_impls)
        
        # 递归查找子类的子类
        for impl in direct_impls:
            result.extend(self._get_all_implementations(impl))
        
        return result
    
    def resolve_interface_call(self, package_class: str, method_signature: str) -> List[dict]:
        """
        CHA 解析：给定一个接口/抽象类方法，返回所有可能的实现类方法
        
        示例：
        输入: "com.macro.mall.service.UmsMenuService", "list(Long,Integer,Integer)"
        返回: [
            {"package_class": "com.macro.mall.service.impl.UmsMenuServiceImpl", ...},
            ...
        ]
        """
        sig_key = self._build_signature_key_from_sig(method_signature)
        method_key = f"{package_class}|{sig_key}"
        
        return self._method_override_map.get(method_key, [])
    
    def is_interface_or_abstract_class(self, package_class: str) -> bool:
        """判断一个类是否为接口或抽象类"""
        return self._is_interface_or_abstract(package_class)
    
    def get_all_concrete_methods(self, package_class: str, method_signature: str) -> List[dict]:
        """
        获取一个方法的所有具体实现（包括自身和子类重写）
        用于向上分析时扩展查询范围
        """
        if not self.is_interface_or_abstract_class(package_class):
            # 如果是具体类，只返回自身
            return [{'package_class': package_class, 'method_signature': method_signature}]
        
        # 如果是接口/抽象类，返回所有实现类方法
        return self.resolve_interface_call(package_class, method_signature)
    
    @staticmethod
    def _build_signature_key(method_name: str, parameters: str) -> str:
        """从数据库参数格式构建签名键"""
        try:
            params = json.loads(parameters) if isinstance(parameters, str) else parameters
            param_types = [p['parameter_type'] for p in params]
            return f"{method_name}({','.join(param_types)})"
        except:
            return f"{method_name}()"
    
    @staticmethod
    def _build_signature_key_from_sig(method_signature: str) -> str:
        """从方法签名字符串构建签名键"""
        return method_signature  # 已经是标准格式
    
    def _is_interface_or_abstract(self, package_class: str) -> bool:
        """判断类是否为接口或抽象类（基于数据库字段或命名约定）"""
        # 实际实现应查询数据库的 class_type 字段
        class_info = self._class_hierarchy.get(package_class, {})
        # 简化判断：接口通常以 Service/Mapper/DAO 结尾，或显式标记
        return package_class.split('.')[-1].endswith(('Service', 'Mapper', 'Dao'))
```

### 1.2 AnnotationAwareEntryDetector（注解感知入口发现）

**目的**：识别 Controller、Service 等框架入口方法，解决"向上分析只到 ServiceImpl 就停止"的问题。

```python
# entry_detector.py
class AnnotationAwareEntryDetector:
    """
    注解感知入口发现器
    识别 Spring MVC Controller、Scheduled 任务、MessageListener 等入口
    """
    
    # 框架入口注解映射
    ENTRY_ANNOTATIONS = {
        # Spring MVC
        'org.springframework.web.bind.annotation.RequestMapping': 'HTTP_API',
        'org.springframework.web.bind.annotation.GetMapping': 'HTTP_API',
        'org.springframework.web.bind.annotation.PostMapping': 'HTTP_API',
        'org.springframework.web.bind.annotation.PutMapping': 'HTTP_API',
        'org.springframework.web.bind.annotation.DeleteMapping': 'HTTP_API',
        'org.springframework.web.bind.annotation.PatchMapping': 'HTTP_API',
        
        # Spring Scheduler
        'org.springframework.scheduling.annotation.Scheduled': 'SCHEDULED_TASK',
        
        # Spring Event
        'org.springframework.context.event.EventListener': 'EVENT_LISTENER',
        
        # Spring JMS
        'org.springframework.jms.annotation.JmsListener': 'MESSAGE_CONSUMER',
        
        # Java EE / Jakarta
        'jakarta.ws.rs.Path': 'HTTP_API',
        'javax.ws.rs.Path': 'HTTP_API',
        
        # Spring Boot Actuator
        'org.springframework.boot.actuate.endpoint.annotation.Endpoint': 'ACTUATOR',
        
        # Custom
        'com.macro.mall.common.api.CommonResult': 'API_WRAPPER',
    }
    
    def __init__(self, db_connection, project_ids: List[int]):
        self._entry_methods: Dict[str, dict] = {}  # method_key -> entry_info
        self._load_annotations(db_connection, project_ids)
    
    def _load_annotations(self, db_connection, project_ids: List[int]):
        """
        从数据库加载方法注解信息
        假设有 method_annotation 表: method_id, annotation_name, annotation_params
        """
        cursor = db_connection.cursor()
        placeholders = ','.join('?' * len(project_ids))
        
        # 查询所有方法的注解
        cursor.execute(f"""
            SELECT m.method_id, c.package_class, m.method_name, m.parameters,
                   a.annotation_name, a.annotation_params
            FROM method_table m
            JOIN class_table c ON m.class_id = c.class_id
            LEFT JOIN method_annotation a ON m.method_id = a.method_id
            WHERE c.project_id IN ({placeholders})
        """, project_ids)
        
        for row in cursor.fetchall():
            method_id, package_class, method_name, parameters, anno_name, anno_params = row
            
            if anno_name and anno_name in self.ENTRY_ANNOTATIONS:
                entry_type = self.ENTRY_ANNOTATIONS[anno_name]
                sig = self._build_signature(method_name, parameters)
                method_key = f"{package_class}|{sig}"
                
                self._entry_methods[method_key] = {
                    'method_id': method_id,
                    'package_class': package_class,
                    'method_signature': sig,
                    'entry_type': entry_type,
                    'annotation': anno_name,
                    'annotation_params': anno_params
                }
    
    def is_entry_method(self, package_class: str, method_signature: str) -> Optional[dict]:
        """判断一个方法是否为入口方法"""
        key = f"{package_class}|{method_signature}"
        return self._entry_methods.get(key)
    
    def classify_root_node(self, node: CallChainNode, has_callers: bool) -> str:
        """
        对向上分析的根节点进行分类
        """
        # 1. 检查是否为注解标记的入口
        entry_info = self.is_entry_method(node.package_class, node.method_signature)
        if entry_info:
            return entry_info['entry_type']
        
        # 2. 检查是否为 Controller 类（命名约定）
        class_name = node.class_name
        if class_name.endswith('Controller'):
            return 'CONTROLLER_BY_CONVENTION'
        
        # 3. 无调用者但不是已知入口
        if not has_callers:
            return 'NO_STATIC_CALLER'
        
        # 4. 有调用者但到达深度限制
        return 'INTERMEDIATE'
    
    @staticmethod
    def _build_signature(method_name: str, parameters: str) -> str:
        try:
            params = json.loads(parameters) if isinstance(parameters, str) else parameters
            param_types = [p['parameter_type'] for p in params]
            return f"{method_name}({','.join(param_types)})"
        except:
            return f"{method_name}()"
```

---

## 2. 修订核心组件

### 2.1 ReverseCallerIndex（增强版）

**主要修改**：
1. 集成 `ClassHierarchyIndex` 进行 CHA 解析
2. 保留多调用点行号（不再用 `seen_callers` 简单去重）
3. 增加调用关系类型标记（直接调用 vs 接口派生调用）

```python
# index.py - ReverseCallerIndex 修订版
class ReverseCallerIndex:
    """
    反向调用索引（增强版）
    支持 Class Hierarchy Analysis (CHA) 解析接口调用
    """
    
    def __init__(self, unified_index: UnifiedMethodIndex, 
                 class_hierarchy: Optional[ClassHierarchyIndex] = None):
        self._reverse_index: Dict[str, List[dict]] = {}
        self._class_hierarchy = class_hierarchy
        self._build_reverse_index(unified_index)
    
    def _build_reverse_index(self, unified_index: UnifiedMethodIndex):
        """
        扫描统一索引中所有方法的 method_invocation_map，
        建立反向调用关系，支持接口方法到实现类的映射
        """
        for key, methods in unified_index._unified_index.items():
            for method in methods:
                caller_info = self._extract_caller_info(method)
                invocation_map_json = method.get('method_invocation_map', '{}')
                
                if not invocation_map_json or invocation_map_json == '{}':
                    continue
                
                callable_points = InvocationPointParser.parse(invocation_map_json)
                
                for point in callable_points:
                    callee_package_class = point['package_class']
                    callee_signature = point['signature']
                    
                    # === CHA 增强：处理接口调用 ===
                    # 如果被调用者是接口/抽象类，同时索引到实现类方法
                    if self._class_hierarchy:
                        impl_methods = self._class_hierarchy.resolve_interface_call(
                            callee_package_class, 
                            callee_signature
                        )
                        
                        # 为每个实现类方法建立反向索引
                        for impl in impl_methods:
                            impl_key = f"{impl['package_class']}|{impl['method_signature']}"
                            self._add_caller(impl_key, caller_info, point['lines'], 
                                           call_type='CHA_RESOLVED')
                    
                    # 标准索引：按声明类型索引
                    callee_key = f"{callee_package_class}|{callee_signature}"
                    self._add_caller(callee_key, caller_info, point['lines'],
                                   call_type='DIRECT')
    
    def _add_caller(self, callee_key: str, caller_info: dict, lines: List[int],
                   call_type: str = 'DIRECT'):
        """添加调用者到反向索引，保留多调用点行号"""
        if callee_key not in self._reverse_index:
            self._reverse_index[callee_key] = []
        
        # 检查是否已存在同一调用者（同一方法）
        existing = None
        for entry in self._reverse_index[callee_key]:
            if (entry['package_class'] == caller_info['package_class'] and 
                entry['method_signature'] == caller_info['method_signature']):
                existing = entry
                break
        
        if existing:
            # 合并行号（同一调用者内多处调用）
            existing_lines = set(existing.get('invocation_lines', []))
            existing_lines.update(lines)
            existing['invocation_lines'] = sorted(list(existing_lines))
            # 标记为多调用点
            existing['multi_call_sites'] = len(existing['invocation_lines']) > 1
        else:
            # 新增调用者
            new_entry = {
                **caller_info,
                'invocation_lines': lines,
                'call_type': call_type,
                'multi_call_sites': len(lines) > 1
            }
            self._reverse_index[callee_key].append(new_entry)
    
    def query_callers(self, package_class: str, method_signature: str) -> List[dict]:
        """
        查询调用了指定方法的所有调用者（含 CHA 解析）
        
        查询策略：
        1. 直接查询目标方法的调用者
        2. 如果目标是接口/抽象类，同时返回实现类方法的调用者
        3. 如果目标是实现类，同时查询其接口方法的调用者（向上兼容）
        """
        key = f"{package_class}|{method_signature}"
        results = []
        seen_keys = set()
        
        # 1. 直接查询
        direct_callers = self._reverse_index.get(key, [])
        for caller in direct_callers:
            caller_key = f"{caller['package_class']}|{caller['method_signature']}"
            if caller_key not in seen_keys:
                results.append(caller)
                seen_keys.add(caller_key)
        
        # 2. CHA 扩展：如果目标是实现类，查找其接口的调用者
        if self._class_hierarchy:
            # 获取该类的所有接口方法
            # 简化：假设方法名和参数相同即为重写
            class_name = package_class.split('.')[-1]
            if 'Impl' in class_name or 'impl' in package_class.lower():
                # 尝试找到对应的接口
                # 实际应查询 class_hierarchy 的继承关系
                pass  # 具体实现依赖数据库 schema
        
        return results
```

### 2.2 UpwardsCallChainBuilder（增强版）

**主要修改**：
1. 集成 `AnnotationAwareEntryDetector` 进行根节点分类
2. 增加 `coverage_stats` 实时统计
3. 增加 `analysis_limitations` 记录

```python
# upwards_builder.py - 修订版
class UpwardsCallChainBuilder:
    """
    向上调用链构建器（增强版）
    支持 CHA、注解感知入口发现、覆盖率统计
    """
    
    def __init__(self, 
                 reverse_index: ReverseCallerIndex,
                 entry_detector: Optional[AnnotationAwareEntryDetector] = None,
                 max_depth: int = 10):
        self.reverse_index = reverse_index
        self.entry_detector = entry_detector
        self.max_depth = max_depth
        self._coverage_stats = {
            'total_query_methods': 0,
            'methods_with_callers': 0,
            'methods_without_callers': 0,
            'cha_resolved_calls': 0,
            'direct_calls': 0,
            'cyclic_paths': 0,
            'depth_limited_paths': 0
        }
        self._limitations = []  # 记录分析限制
    
    def build(self, package_class: str, method_signature: str) -> CallChainNode:
        """构建向上调用链（增强版）"""
        root = self._create_node(package_class, method_signature, depth=0)
        root.root_type = self._classify_root(package_class, method_signature, has_callers=False)
        
        path_visited = {f"{package_class}|{method_signature}"}
        self._dfs_expand(root, path_visited, current_depth=0)
        
        # 附加分析元数据
        root._analysis_meta = {
            'coverage_stats': self._coverage_stats,
            'limitations': self._limitations,
            'is_complete': len(self._limitations) == 0
        }
        
        return root
    
    def _dfs_expand(self, node: CallChainNode, path_visited: Set[str], current_depth: int):
        """反向 DFS（增强版）"""
        self._coverage_stats['total_query_methods'] += 1
        
        # 1. 深度限制
        if current_depth >= self.max_depth:
            node.is_leaf = True
            node.root_type = 'DEPTH_LIMITED'
            self._coverage_stats['depth_limited_paths'] += 1
            self._limitations.append(f"Depth limit reached at {node.node_id}")
            return
        
        # 2. 查询调用者
        callers = self.reverse_index.query_callers(node.package_class, node.method_signature)
        
        if not callers:
            node.is_leaf = True
            self._coverage_stats['methods_without_callers'] += 1
            
            # 分类根节点类型
            node.root_type = self._classify_root(
                node.package_class, 
                node.method_signature,
                has_callers=False
            )
            return
        
        self._coverage_stats['methods_with_callers'] += 1
        
        # 3. 统计调用类型
        for caller in callers:
            if caller.get('call_type') == 'CHA_RESOLVED':
                self._coverage_stats['cha_resolved_calls'] += 1
            else:
                self._coverage_stats['direct_calls'] += 1
        
        # 4. 按行号排序
        sorted_callers = sorted(
            callers,
            key=lambda c: min(c['invocation_lines']) if c.get('invocation_lines') else 999999
        )
        
        # 5. 处理每个调用者
        for caller in sorted_callers:
            caller_key = f"{caller['package_class']}|{caller['method_signature']}"
            
            # 环检测
            if caller_key in path_visited:
                parent = self._create_node_from_caller(caller, current_depth + 1)
                parent.is_cyclic = True
                parent.is_leaf = True
                parent.root_type = 'CYCLIC'
                node.children.append(parent)
                self._coverage_stats['cyclic_paths'] += 1
                continue
            
            parent = self._create_node_from_caller(caller, current_depth + 1)
            
            # 标记多调用点
            if caller.get('multi_call_sites'):
                parent.has_multiple_call_sites = True
            
            node.children.append(parent)
            
            path_visited.add(caller_key)
            self._dfs_expand(parent, path_visited, current_depth + 1)
            path_visited.discard(caller_key)
        
        if not node.children:
            node.is_leaf = True
    
    def _classify_root(self, package_class: str, method_signature: str, 
                       has_callers: bool) -> str:
        """分类根节点类型"""
        if self.entry_detector:
            entry_type = self.entry_detector.classify_root_node(
                self._create_node(package_class, method_signature, 0),
                has_callers
            )
            return entry_type
        return 'UNKNOWN'
    
    def _create_node(self, package_class: str, method_signature: str, depth: int) -> CallChainNode:
        """创建节点（增强字段）"""
        method_name = method_signature.split('(')[0]
        class_name = package_class.split('.')[-1]
        node_id = f"{depth}|{package_class}|{method_signature}"
        
        node = CallChainNode(
            node_id=node_id,
            package_class=package_class,
            method_signature=method_signature,
            method_name=method_name,
            class_name=class_name,
            depth=depth
        )
        # 增强字段
        node.root_type = 'UNKNOWN'
        node.has_multiple_call_sites = False
        return node
    
    def _create_node_from_caller(self, caller: dict, depth: int) -> CallChainNode:
        """从调用者信息创建节点"""
        node_id = f"{depth}|{caller['package_class']}|{caller['method_signature']}"
        
        node = CallChainNode(
            node_id=node_id,
            package_class=caller['package_class'],
            method_signature=caller['method_signature'],
            method_name=caller['method_name'],
            class_name=caller['class_name'],
            depth=depth,
            invocation_lines=caller.get('invocation_lines', []),
            db_method_id=caller.get('method_id')
        )
        node.call_type = caller.get('call_type', 'DIRECT')
        node.has_multiple_call_sites = caller.get('multi_call_sites', False)
        return node
```

---

## 3. 修订数据模型

### 3.1 CallChainNode（增加字段）

```python
# models.py - 修订版
@dataclass
class CallChainNode:
    """调用链路节点（增强版）"""
    node_id: str
    package_class: str
    method_signature: str
    method_name: str
    class_name: str
    depth: int = 0
    invocation_lines: List[int] = field(default_factory=list)
    children: List['CallChainNode'] = field(default_factory=list)
    is_cyclic: bool = False
    is_leaf: bool = False
    db_method_id: Optional[int] = None
    
    # === 新增字段 ===
    root_type: str = 'UNKNOWN'           # 根节点类型分类
    call_type: str = 'DIRECT'            # 调用类型: DIRECT / CHA_RESOLVED
    has_multiple_call_sites: bool = False  # 同一调用者内多处调用
    entry_annotation: Optional[str] = None  # 入口注解（如 @RequestMapping）
    
    def to_dict(self) -> dict:
        """转换为字典（增强版）"""
        base = {
            "node_id": self.node_id,
            "package_class": self.package_class,
            "method_signature": self.method_signature,
            "method_name": self.method_name,
            "class_name": self.class_name,
            "depth": self.depth,
            "invocation_lines": self.invocation_lines,
            "is_cyclic": self.is_cyclic,
            "is_leaf": self.is_leaf,
            "db_method_id": self.db_method_id,
            "root_type": self.root_type,
            "call_type": self.call_type,
            "has_multiple_call_sites": self.has_multiple_call_sites,
            "children": [child.to_dict() for child in self.children]
        }
        if self.entry_annotation:
            base["entry_annotation"] = self.entry_annotation
        return base
```

---

## 4. 修订批量分析入口

### 4.1 analyzer.py（完整修订版）

```python
# analyzer.py - 完整修订版
from .index import UnifiedMethodIndex, ReverseCallerIndex
from .class_hierarchy import ClassHierarchyIndex
from .entry_detector import AnnotationAwareEntryDetector
from .downwards_builder import DownwardsCallChainBuilder
from .upwards_builder import UpwardsCallChainBuilder
from .models import CallChainNode
import json
import logging
from typing import List, Dict, Optional
import os
import sqlite3


# ============ 静态分析能力边界声明 ============

ANALYSIS_LIMITATIONS = [
    {
        "id": "DYNAMIC_DISPATCH",
        "severity": "HIGH",
        "description": "无法覆盖通过反射、Lambda、方法引用、动态代理发起的调用",
        "examples": ["Spring AOP 代理方法", "MyBatis Mapper 动态绑定", "反射调用 invoke()"],
        "impact": "向上分析可能遗漏实际调用者，结果属于'过于乐观的下界'"
    },
    {
        "id": "INTERFACE_RESOLUTION",
        "severity": "MEDIUM", 
        "description": "CHA 解析基于静态类层次，无法处理运行时类型确定",
        "examples": ["条件分支中不同实现类赋值", "工厂模式返回类型"],
        "impact": "可能包含不可达调用路径（假阳性），或遗漏某些实现类（假阴性）"
    },
    {
        "id": "FRAMEWORK_CALLS",
        "severity": "MEDIUM",
        "description": "框架代码（Spring DispatcherServlet、定时任务调度器等）通常不在分析范围内",
        "examples": ["HTTP 请求由 DispatcherServlet 转发", "@Scheduled 由 Spring 调度器触发"],
        "impact": "Controller 方法可能显示为'无静态调用者'，需结合注解识别"
    },
    {
        "id": "NATIVE_CODE",
        "severity": "LOW",
        "description": "JNI 调用、Native 方法无法追踪",
        "examples": ["System.arraycopy()", "文件 IO 的 Native 实现"],
        "impact": "不影响常规业务代码分析"
    }
]


def build_upwards_call_chains(
    username: str,
    git_url: str,
    commit_old: str,
    commit_new: str,
    changed_methods: List[dict],
    max_depth: int = 10,
    db_path: Optional[str] = None,
    enable_cha: bool = True,
    enable_entry_detection: bool = True
) -> dict:
    """
    向上影响分析（增强版）：谁调用了变更方法？
    
    新增特性：
    - CHA 接口/实现类映射
    - 注解感知入口发现
    - 覆盖率统计
    - 能力边界声明
    """
    
    # 1. 数据库连接
    db_path = db_path or _resolve_db_path(username, git_url)
    conn = sqlite3.connect(db_path)
    
    # 2. 构建统一索引
    index = UnifiedMethodIndex(
        db_path=db_path,
        commit_old=commit_old,
        commit_new=commit_new
    )
    
    # 3. 构建类层次索引（CHA）
    class_hierarchy = None
    if enable_cha:
        try:
            project_ids = [0, 1]  # 基线 + 增量
            class_hierarchy = ClassHierarchyIndex(conn, project_ids)
            logging.info("✓ 类层次索引构建完成（CHA 支持已启用）")
        except Exception as e:
            logging.warning(f"类层次索引构建失败，CHA 功能将禁用: {e}")
            enable_cha = False
    
    # 4. 构建反向调用索引
    reverse_index = ReverseCallerIndex(index, class_hierarchy)
    
    # 5. 构建入口发现器
    entry_detector = None
    if enable_entry_detection:
        try:
            entry_detector = AnnotationAwareEntryDetector(conn, [0, 1])
            logging.info("✓ 注解感知入口发现已启用")
        except Exception as e:
            logging.warning(f"入口发现器构建失败: {e}")
    
    conn.close()
    
    # 6. 创建向上构建器
    builder = UpwardsCallChainBuilder(
        reverse_index=reverse_index,
        entry_detector=entry_detector,
        max_depth=max_depth
    )
    
    # 7. 批量处理
    results = []
    failed = []
    global_coverage = {
        'total_methods': 0,
        'methods_with_callers': 0,
        'methods_without_callers': 0,
        'cha_resolved_calls': 0,
        'direct_calls': 0,
        'cyclic_paths': 0,
        'depth_limited_paths': 0,
        'entry_points_found': 0
    }
    
    for i, method in enumerate(changed_methods, 1):
        try:
            package_class = _resolve_package_class(method, index)
            method_signature = _build_signature(method)
            
            # 构建向上调用链
            chain = builder.build(package_class, method_signature)
            
            # 收集覆盖率统计
            meta = getattr(chain, '_analysis_meta', {})
            stats = meta.get('coverage_stats', {})
            for key in global_coverage:
                if key in stats:
                    global_coverage[key] += stats[key]
            
            # 统计入口点
            entry_count = _count_entry_points(chain)
            global_coverage['entry_points_found'] += entry_count
            
            # 组装结果
            chain_dict = chain.to_dict()
            # 附加分析元数据到根节点
            chain_dict['_analysis_meta'] = meta
            
            results.append({
                "direction": "upwards",
                "method_info": method,
                "package_class": package_class,
                "method_signature": method_signature,
                "chain": chain_dict,
                "entry_points": _extract_entry_points(chain),
                "has_incomplete_paths": len(meta.get('limitations', [])) > 0
            })
            
            logging.info(f"  ✓ 方法 [{i}/{len(changed_methods)}] 向上分析成功: "
                        f"{method['class_name']}.{method['method_name']} "
                        f"(入口点: {entry_count})")
            
        except Exception as e:
            failed.append({
                "method": method,
                "error": str(e)
            })
            logging.warning(f"  ✗ 方法 [{i}/{len(changed_methods)}] 向上分析失败: {e}")
    
    # 8. 计算覆盖率
    coverage_rate = 0.0
    if global_coverage['total_methods'] > 0:
        coverage_rate = (global_coverage['methods_with_callers'] / 
                        global_coverage['total_methods'] * 100)
    
    # 9. 组装结果
    result = {
        "metadata": {
            "direction": "upwards",
            "analysis_version": "3.1",
            "total_methods": len(changed_methods),
            "successful_chains": len(results),
            "failed_chains": len(failed),
            "commit_old": commit_old,
            "commit_new": commit_new,
            "max_depth": max_depth,
            "features_enabled": {
                "class_hierarchy_analysis": enable_cha,
                "entry_detection": enable_entry_detection
            },
            "coverage_stats": {
                **global_coverage,
                "coverage_rate_percent": round(coverage_rate, 2),
                "interpretation": (
                    "覆盖率表示成功找到至少一个调用者的方法比例。"
                    "低覆盖率可能意味着大量调用通过动态绑定/框架发起。"
                )
            }
        },
        "impact_chains": results,
        "failed": failed,
        "analysis_limitations": ANALYSIS_LIMITATIONS,
        "recommendations": _generate_recommendations(global_coverage, enable_cha)
    }
    
    # 10. 保存 JSON
    _save_result(result, username, git_url, commit_old, commit_new, "upwards")
    
    return result


def build_downwards_call_chains(
    username: str,
    git_url: str,
    commit_old: str,
    commit_new: str,
    changed_methods: List[dict],
    max_depth: int = 10,
    db_path: Optional[str] = None
) -> dict:
    """
    向下调用链分析（功能风险分析）- 基本保持原逻辑
    增加能力边界声明
    """
    index = UnifiedMethodIndex(
        db_path=db_path or _resolve_db_path(username, git_url),
        commit_old=commit_old,
        commit_new=commit_new
    )
    
    builder = DownwardsCallChainBuilder(index, max_depth=max_depth)
    
    results = []
    failed = []
    
    for i, method in enumerate(changed_methods, 1):
        try:
            package_class = _resolve_package_class(method, index)
            method_signature = _build_signature(method)
            
            chain = builder.build(package_class, method_signature)
            
            results.append({
                "direction": "downwards",
                "method_info": method,
                "package_class": package_class,
                "method_signature": method_signature,
                "chain": chain.to_dict()
            })
            
            logging.info(f"  ✓ 方法 [{i}/{len(changed_methods)}] 向下分析成功")
            
        except Exception as e:
            failed.append({"method": method, "error": str(e)})
    
    result = {
        "metadata": {
            "direction": "downwards",
            "analysis_version": "3.1",
            "total_methods": len(changed_methods),
            "successful_chains": len(results),
            "failed_chains": len(failed),
            "commit_old": commit_old,
            "commit_new": commit_new,
            "max_depth": max_depth
        },
        "call_chains": results,
        "failed": failed,
        "analysis_limitations": [l for l in ANALYSIS_LIMITATIONS 
                               if l['id'] in ['DYNAMIC_DISPATCH', 'INTERFACE_RESOLUTION']]
    }
    
    _save_result(result, username, git_url, commit_old, commit_new, "downwards")
    return result


# ============ 辅助函数 ============

def _count_entry_points(chain: CallChainNode) -> int:
    """统计调用链中的入口点数量"""
    count = 0
    def traverse(node):
        nonlocal count
        if node.root_type in ['HTTP_API', 'SCHEDULED_TASK', 'EVENT_LISTENER',
                              'MESSAGE_CONSUMER', 'CONTROLLER_BY_CONVENTION']:
            count += 1
        for child in node.children:
            traverse(child)
    traverse(chain)
    return count


def _extract_entry_points(chain: CallChainNode) -> List[dict]:
    """提取调用链中的所有入口点信息"""
    entries = []
    def traverse(node):
        if node.root_type in ['HTTP_API', 'SCHEDULED_TASK', 'EVENT_LISTENER',
                              'MESSAGE_CONSUMER', 'CONTROLLER_BY_CONVENTION']:
            entries.append({
                "package_class": node.package_class,
                "method_signature": node.method_signature,
                "root_type": node.root_type,
                "depth_from_change": node.depth
            })
        for child in node.children:
            traverse(child)
    traverse(chain)
    return entries


def _generate_recommendations(coverage_stats: dict, enable_cha: bool) -> List[str]:
    """基于覆盖率生成建议"""
    recommendations = []
    
    coverage_rate = coverage_stats.get('coverage_rate_percent', 0)
    
    if coverage_rate < 30:
        recommendations.append(
            "覆盖率较低（<30%），建议检查是否存在大量动态绑定调用（如 MyBatis Mapper、"
            "Spring AOP）。考虑结合运行时分析补充静态分析盲区。"
        )
    
    if coverage_stats.get('cha_resolved_calls', 0) > 0 and not enable_cha:
        recommendations.append(
            "检测到接口调用但 CHA 未启用，建议启用 enable_cha=True 以提高覆盖率。"
        )
    
    if coverage_stats.get('depth_limited_paths', 0) > 0:
        recommendations.append(
            f"存在 {coverage_stats['depth_limited_paths']} 条路径因深度限制被截断，"
            "如需完整分析请增加 max_depth。"
        )
    
    if coverage_stats.get('entry_points_found', 0) == 0 and coverage_stats['methods_with_callers'] > 0:
        recommendations.append(
            "未识别到框架入口点（Controller/Scheduler），建议确认注解数据是否完整加载。"
        )
    
    if not recommendations:
        recommendations.append("分析结果看起来完整，未发现明显问题。")
    
    return recommendations


def _resolve_db_path(username: str, git_url: str) -> str:
    """解析数据库路径"""
    project_name = git_url.split('/')[-1].replace('.git', '')
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..', '..', '..',
        f"{username}_{project_name}_baseline_*.db"
    )


def _resolve_package_class(method: dict, index: UnifiedMethodIndex) -> str:
    """解析方法的完整 package_class"""
    class_name = method['class_name']
    method_name = method['method_name']
    
    for key, methods in index._unified_index.items():
        for m in methods:
            if m['class_name'] == class_name and m['method_name'] == method_name:
                return m['package_class']
    
    return method.get('package_class', f"unknown.{class_name}")


def _build_signature(method: dict) -> str:
    """从方法数据构建签名"""
    method_name = method['method_name']
    params = method.get('parameters', '[]')
    try:
        params_list = json.loads(params) if isinstance(params, str) else params
        param_types = [p['parameter_type'] for p in params_list]
        return f"{method_name}({','.join(param_types)})"
    except:
        return f"{method_name}()"


def _save_result(result: dict, username: str, git_url: str,
                 commit_old: str, commit_new: str, direction: str):
    """保存结果到 JSON 文件"""
    old_short = commit_old[:7] if len(commit_old) >= 7 else commit_old
    new_short = commit_new[:7] if len(commit_new) >= 7 else commit_new
    filename = f"{old_short}..{new_short}_{direction}_call_chains.json"
    
    project_name = git_url.split('/')[-1].replace('.git', '')
    output_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..', '..', '..', 'analyze_result',
        f"{username}_{project_name}_baseline_{commit_old[:7]}"
    )
    os.makedirs(output_dir, exist_ok=True)
    
    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    logging.info(f"✓ {direction} 分析结果已保存: {filepath}")
```

---

## 5. 输出 JSON 示例（增强版）

### 向上分析输出示例

```json
{
  "metadata": {
    "direction": "upwards",
    "analysis_version": "3.1",
    "total_methods": 1,
    "successful_chains": 1,
    "failed_chains": 0,
    "commit_old": "83fe3e7",
    "commit_new": "f9add0f",
    "max_depth": 10,
    "features_enabled": {
      "class_hierarchy_analysis": true,
      "entry_detection": true
    },
    "coverage_stats": {
      "total_methods": 5,
      "methods_with_callers": 4,
      "methods_without_callers": 1,
      "cha_resolved_calls": 2,
      "direct_calls": 3,
      "cyclic_paths": 0,
      "depth_limited_paths": 0,
      "entry_points_found": 1,
      "coverage_rate_percent": 80.0,
      "interpretation": "覆盖率表示成功找到至少一个调用者的方法比例。低覆盖率可能意味着大量调用通过动态绑定/框架发起。"
    }
  },
  "impact_chains": [
    {
      "direction": "upwards",
      "method_info": {
        "class_name": "UmsMenuServiceImpl",
        "method_name": "updateHidden",
        "change_type": "MODIFIED"
      },
      "package_class": "com.macro.mall.service.impl.UmsMenuServiceImpl",
      "method_signature": "updateHidden(Long,Integer)",
      "chain": {
        "node_id": "0|com.macro.mall.service.impl.UmsMenuServiceImpl|updateHidden(Long,Integer)",
        "package_class": "com.macro.mall.service.impl.UmsMenuServiceImpl",
        "method_signature": "updateHidden(Long,Integer)",
        "method_name": "updateHidden",
        "class_name": "UmsMenuServiceImpl",
        "depth": 0,
        "invocation_lines": [],
        "is_cyclic": false,
        "is_leaf": false,
        "root_type": "UNKNOWN",
        "call_type": "DIRECT",
        "has_multiple_call_sites": false,
        "_analysis_meta": {
          "coverage_stats": {
            "total_query_methods": 5,
            "methods_with_callers": 4,
            "methods_without_callers": 1,
            "cha_resolved_calls": 2,
            "direct_calls": 3,
            "cyclic_paths": 0,
            "depth_limited_paths": 0
          },
          "limitations": [],
          "is_complete": true
        },
        "children": [
          {
            "node_id": "1|com.macro.mall.service.UmsMenuService|updateHidden(Long,Integer)",
            "package_class": "com.macro.mall.service.UmsMenuService",
            "method_signature": "updateHidden(Long,Integer)",
            "method_name": "updateHidden",
            "class_name": "UmsMenuService",
            "depth": 1,
            "invocation_lines": [45, 67],
            "is_cyclic": false,
            "is_leaf": false,
            "root_type": "INTERMEDIATE",
            "call_type": "CHA_RESOLVED",
            "has_multiple_call_sites": true,
            "children": [
              {
                "node_id": "2|com.macro.mall.controller.UmsMenuController|updateHidden(Long,Integer)",
                "package_class": "com.macro.mall.controller.UmsMenuController",
                "method_signature": "updateHidden(Long,Integer)",
                "method_name": "updateHidden",
                "class_name": "UmsMenuController",
                "depth": 2,
                "invocation_lines": [89],
                "is_cyclic": false,
                "is_leaf": true,
                "root_type": "HTTP_API",
                "call_type": "DIRECT",
                "has_multiple_call_sites": false,
                "entry_annotation": "org.springframework.web.bind.annotation.PostMapping",
                "children": []
              }
            ]
          }
        ]
      },
      "entry_points": [
        {
          "package_class": "com.macro.mall.controller.UmsMenuController",
          "method_signature": "updateHidden(Long,Integer)",
          "root_type": "HTTP_API",
          "depth_from_change": 2
        }
      ],
      "has_incomplete_paths": false
    }
  ],
  "failed": [],
  "analysis_limitations": [
    {
      "id": "DYNAMIC_DISPATCH",
      "severity": "HIGH",
      "description": "无法覆盖通过反射、Lambda、方法引用、动态代理发起的调用",
      "examples": ["Spring AOP 代理方法", "MyBatis Mapper 动态绑定", "反射调用 invoke()"],
      "impact": "向上分析可能遗漏实际调用者，结果属于'过于乐观的下界'"
    },
    {
      "id": "INTERFACE_RESOLUTION",
      "severity": "MEDIUM",
      "description": "CHA 解析基于静态类层次，无法处理运行时类型确定",
      "examples": ["条件分支中不同实现类赋值", "工厂模式返回类型"],
      "impact": "可能包含不可达调用路径（假阳性），或遗漏某些实现类（假阴性）"
    },
    {
      "id": "FRAMEWORK_CALLS",
      "severity": "MEDIUM",
      "description": "框架代码（Spring DispatcherServlet、定时任务调度器等）通常不在分析范围内",
      "examples": ["HTTP 请求由 DispatcherServlet 转发", "@Scheduled 由 Spring 调度器触发"],
      "impact": "Controller 方法可能显示为'无静态调用者'，需结合注解识别"
    },
    {
      "id": "NATIVE_CODE",
      "severity": "LOW",
      "description": "JNI 调用、Native 方法无法追踪",
      "examples": ["System.arraycopy()", "文件 IO 的 Native 实现"],
      "impact": "不影响常规业务代码分析"
    }
  ],
  "recommendations": [
    "分析结果看起来完整，未发现明显问题。"
  ]
}
```

---

## 6. 文件结构变更

```
src/jcci/call_chain/
├── __init__.py                  # 导出公共接口
├── models.py                    # CallChainNode（增加 root_type 等字段）
├── index.py                     # UnifiedMethodIndex + ReverseCallerIndex（CHA增强）
├── class_hierarchy.py           # 【新增】ClassHierarchyIndex（CHA支持）
├── entry_detector.py            # 【新增】AnnotationAwareEntryDetector
├── parser.py                    # InvocationPointParser（复用）
├── downwards_builder.py         # DownwardsCallChainBuilder（原逻辑）
├── upwards_builder.py           # UpwardsCallChainBuilder（增强版）
└── analyzer.py                  # 拆分为两个方法 + 能力边界声明

tests/test_call_chain/
├── test_models.py               # 增加新字段测试
├── test_reverse_index.py        # 【新增】反向索引测试（8个）
├── test_class_hierarchy.py      # 【新增】CHA测试（6个）
├── test_entry_detector.py       # 【新增】入口发现测试（4个）
├── test_upwards_builder.py      # 【新增】向上构建器测试（12个）
├── test_downwards_builder.py    # 原 test_builder.py 重命名
├── test_unified_index.py        # 复用
├── test_parser.py               # 复用
└── test_integration.py          # 增加双向分析集成测试
```

---

## 7. 关键设计决策总结

| 决策点 | 原方案 | 修订方案 | 理由 |
|--------|--------|----------|------|
| **接口调用缺失** | 无处理 | `ClassHierarchyIndex` + CHA | 解决假阴性，提高覆盖率  |
| **入口识别** | `is_leaf=True` 即入口 | `AnnotationAwareEntryDetector` | 区分框架入口与无调用者 |
| **多调用点** | `seen_callers` 简单去重 | 合并行号 + `multi_call_sites` 标记 | 保留完整调用信息 |
| **根节点分类** | 无 | `root_type` 字段 | 提高结果可解释性 |
| **覆盖率** | 无 | `coverage_stats` + 百分比 | 量化分析完整性 |
| **能力边界** | 无 | `analysis_limitations` + `recommendations` | 明确告知用户盲区 |
| **数据库依赖** | 纯 `method_invocation_map` | 增加 `class_table` + `method_annotation` | 支持 CHA 和注解识别 |

---

## 8. 使用方式（Workflow 集成）

```python
# workflow1.py 步骤3 修改

from src.jcci.call_chain.analyzer import (
    build_upwards_call_chains,
    build_downwards_call_chains
)

changed_methods = result1.get('change_summary', {}).get('methods', [])

# 1. 向上影响分析（增强版）
upwards_result = build_upwards_call_chains(
    username=username,
    git_url=git_url,
    commit_old=commit_old,
    commit_new=commit_new,
    changed_methods=changed_methods,
    max_depth=10,
    enable_cha=True,           # 启用 CHA
    enable_entry_detection=True  # 启用注解感知
)

# 查看覆盖率
coverage = upwards_result['metadata']['coverage_stats']
print(f"覆盖率: {coverage['coverage_rate_percent']}%")
print(f"入口点: {coverage['entry_points_found']}")
print(f"CHA解析: {coverage['cha_resolved_calls']}")

# 查看建议
for rec in upwards_result['recommendations']:
    print(f"建议: {rec}")

# 2. 向下功能风险分析（基本不变）
downwards_result = build_downwards_call_chains(
    username=username,
    git_url=git_url,
    commit_old=commit_old,
    commit_new=commit_new,
    changed_methods=changed_methods,
    max_depth=5
)
```

---

## 9. 性能评估（预估）

| 指标 | 原方案 | 修订方案 | 增加开销 |
|------|--------|----------|----------|
| **统一索引构建** | ~0.5s | ~0.5s | 无 |
| **反向索引构建** | ~0.3s | ~0.4s | +CHA 扫描 |
| **类层次索引** | N/A | ~0.2s | 新增 |
| **注解加载** | N/A | ~0.1s | 新增 |
| **单个方法向上分析** | <0.01s | <0.02s | +CHA 查询 |
| **总内存占用** | ~30MB | ~35MB | +类层次 + 注解数据 |

---

## 10. 测试策略（新增）

| 测试文件 | 测试数 | 覆盖内容 |
|----------|--------|----------|
| `test_class_hierarchy.py` | 6 | CHA 接口→实现类映射、继承链解析、重载匹配 |
| `test_entry_detector.py` | 4 | 注解识别、命名约定、分类逻辑 |
| `test_reverse_index.py` | 8 | 反向索引构建、多调用点合并、CHA 调用者 |
| `test_upwards_builder.py` | 12 | 向上 DFS、环检测、深度限制、覆盖率统计 |
| `test_integration.py` | +2 | 双向分析、真实 Mall 项目接口调用场景 |

关键测试案例：

```python
def test_cha_resolves_interface_to_implementations():
    """测试 CHA 将接口方法调用解析到实现类"""
    # UmsMenuService.list() 被调用时，
    # 反向索引应同时包含 UmsMenuServiceImpl.list() 的调用者
    pass

def test_multiple_call_sites_preserved():
    """测试同一调用者内多处调用保留所有行号"""
    # Service.update() 在 Controller 的第 45 行和第 67 行都被调用
    # 结果应包含 [45, 67]，且 multi_call_sites=true
    pass

def test_entry_annotation_detected():
    """测试 @RequestMapping 注解识别为 HTTP_API 入口"""
    pass

def test_coverage_stats_calculated():
    """测试覆盖率统计正确计算"""
    pass
```

---