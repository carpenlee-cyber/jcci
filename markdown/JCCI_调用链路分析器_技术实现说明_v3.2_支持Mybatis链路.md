# JCCI 调用链路分析器 v3.2 技术实现说明

**版本**: v3.2  
**更新日期**: 2026-05-11  
**目标**: 解决 v3.1 关键缺陷，实现精准影响分析

---

## 一、v3.2 核心改进概览

| 改进项 | v3.1 状态 | v3.2 改进 | 优先级 |
|--------|-----------|-----------|--------|
| **DELETED 方法调用链分析** | 缺失破坏性影响标记 | 新增删除方法影响面分析与编译失败预警，增加数据一致性同步点 | P0 |
| **CHA (类层次分析) 启用** | 未真正生效 | 修复接口多态调用追踪，支持实现类自动解析，优化内存索引结构 | P1 |
| **字段级变更分析** | `_mark_field_changes()` 为空 | 完整实现字段 ADDED/MODIFIED/DELETED 标记，采用 AST + 文本搜索两阶段影响追踪 | P2 |
| **MyBatis Mapper 链路** | 仅解析 XML 变更，未关联方法 | 建立 Mapper 方法 ↔ SQL 语句 ↔ DAO 层的完整调用链，改用 XML 解析器避免正则陷阱 | P4 |
| **方法签名严格匹配** | 仅匹配方法名，不验证参数 | 跨版本参数签名一致性校验，重载方法精确识别，支持多对一合并场景 | P3 |
| **Commit 范围显示** | 显示 N/A..N/A | 修复元数据传递，确保报告准确性 | P5 |
| **数据一致性保障** | 未定义事务边界 | 增加显式事务边界与缓存版本兼容性处理 | P2 |

---

## 二、DELETED 方法影响面分析 (P0)

### 2.1 问题定义

v3.1 能识别 DELETED 方法，但在调用链分析中未特殊处理。删除方法会导致所有调用方编译失败，但系统未提供预警。此外，v3.2 需解决数据一致性窗口问题：标记删除方法与构建反向索引之间存在时序风险，可能导致调用方漏报。

### 2.2 技术实现

#### 2.2.1 删除方法标记增强

在 `change_type_analyzer.py` 中增强 `_mark_method_changes`：

```python
def _mark_method_changes(self, diff_parse_map, project_id, commit_new, commit_old):
    """增强版方法变更标记，支持删除方法影响面分析"""
    for filepath, diff_info in diff_parse_map.items():
        removed_lines_set = set(diff_info.get('line_num_removed', []))
        
        # 场景 A: 基线中的 DELETED 方法 (project_id = 0)
        if project_id == 0:
            self._mark_deleted_methods_in_baseline(filepath, removed_lines_set)
        else:
            # 场景 B: 增量中的 ADDED/MODIFIED (原有逻辑)
            self._mark_added_modified_methods(filepath, project_id, commit_new, commit_old)
            
def _mark_deleted_methods_in_baseline(self, filepath, removed_lines_set):
    """标记基线中被删除的方法，并记录删除影响"""
    # 查询基线中该文件的所有方法
    methods = self.db.query(
        "SELECT method_id, class_id, method_name, parameters, start_line, end_line "
        "FROM methods m JOIN class c ON m.class_id = c.class_id "
        "WHERE c.filepath LIKE ? AND m.project_id = 0",
        (f'%{filepath}',)
    )
    
    deleted_methods = []
    for method in methods:
        method_lines = set(range(method['start_line'], method['end_line'] + 1))
        if method_lines.issubset(removed_lines_set):
            # 标记为 DELETED
            self.db.execute(
                "UPDATE methods SET change_type = 'DELETED', is_deleted = 1 "
                "WHERE method_id = ?", (method['method_id'],)
            )
            deleted_methods.append({
                'method_id': method['method_id'],
                'class_id': method['class_id'],
                'method_name': method['method_name'],
                'parameters': method['parameters'],
                'signature': f"{method['method_name']}({self._parse_params(method['parameters'])})"
            })
    
    # 记录删除影响：保存到 deleted_method_impact 表供后续分析
    self._save_deleted_method_impact(deleted_methods)
```

#### 2.2.2 删除方法影响面分析器 (新增模块)

新增 `src/jcci/call_chain/deleted_analyzer.py`：

```python
class DeletedMethodImpactAnalyzer:
    """分析被删除方法的破坏性影响"""
    
    def __init__(self, db_helper, reverse_index):
        self.db = db_helper
        self.reverse_index = reverse_index
        
    def analyze_impact(self, deleted_methods: List[Dict]) -> Dict:
        """
        分析删除方法的影响面
        
        Returns:
            {
                'deleted_methods': [...],
                'impact_summary': {
                    'total_callers': 16,
                    'compile_failures': 16,
                    'affected_entries': 5
                },
                'impact_chains': [...]
            }
        """
        impact_chains = []
        
        for method in deleted_methods:
            # 构建方法签名键
            method_key = self._build_method_key(method)
            
            # 查询所有调用方（使用反向索引）
            callers = self.reverse_index.query_callers(
                method['package_class'], 
                method['signature']
            )
            
            chain = {
                'deleted_method': method,
                'severity': 'CRITICAL',
                'warning': f"方法 {method['signature']} 已被删除，所有调用方将面临编译失败",
                'callers': [],
                'entry_points': []
            }
            
            for caller in callers:
                caller_info = {
                    'class': caller['class_name'],
                    'method': caller['method_signature'],
                    'file': caller['filepath'],
                    'line': caller['call_line'],
                    'impact': 'COMPILE_ERROR'
                }
                chain['callers'].append(caller_info)
                
                # 追溯至入口点
                entry = self._trace_to_entry(caller)
                if entry:
                    chain['entry_points'].append(entry)
            
            impact_chains.append(chain)
            
        return {
            'deleted_methods': deleted_methods,
            'impact_summary': self._summarize_impact(impact_chains),
            'impact_chains': impact_chains
        }
    
    def _trace_to_entry(self, caller: Dict) -> Optional[Dict]:
        """追溯调用方到入口点"""
        # 复用 UpwardsCallChainBuilder 的入口检测逻辑
        from .entry_detector import AnnotationAwareEntryDetector
        detector = AnnotationAwareEntryDetector()
        
        if detector.is_entry_point(caller['annotations']):
            return {
                'type': detector.classify_entry(caller['annotations']),
                'path': caller.get('api_path', 'N/A'),
                'class': caller['class_name'],
                'method': caller['method_signature']
            }
        return None
```

#### 2.2.3 向上调用链构建器增强

修改 `upwards_builder.py` 中的 `_dfs_expand`：

```python
def _dfs_expand(self, node, path_visited, current_depth):
    """增强 DFS，支持删除方法的特殊处理"""
    
    # 如果是删除方法，直接标记为高风险并停止向上追溯
    if node.change_type == 'DELETED':
        node.is_leaf = True
        node.root_type = 'DELETED_METHOD'
        node.severity = 'CRITICAL'
        node.warning = "此方法已被删除，调用方将编译失败"
        return
    
    callers = self.reverse_index.query_callers(
        node.package_class, 
        node.method_signature
    )
    
    if not callers:
        node.is_leaf = True
        node.root_type = self._classify_root(node)
        return
    
    # ... 原有逻辑
```

#### 2.2.4 数据一致性保障（新增）

在 `analyze.py` 的 `analyze_two_commit_incremental()` 中增加同步点，确保 DELETED 标记完成后才构建索引：

```python
def analyze_two_commit_incremental(self, ...):
    # 1. 全量解析基线
    # 2. 增量解析新版本
    # 3. 标记变更类型
    self.change_type_analyzer.analyze_and_mark_changes(...)
    
    # 4. 强制等待数据写入完成（同步点）
    self.db.commit()  # 确保所有标记已持久化
    
    # 5. 验证 DELETED 方法的数据完整性
    deleted_count = self.db.query_one(
        "SELECT COUNT(*) FROM methods WHERE change_type='DELETED'"
    )[0]
    logger.info(f"DELETED 方法标记完成: {deleted_count}个")
    
    # 6. 现在安全构建 UnifiedMethodIndex
    unified_index = UnifiedMethodIndex(self.db, project_id=0)
    unified_index.merge_project(project_id=1)
```

### 2.3 输出示例

```
🔴 删除方法影响分析 (2个):
  1. UserService.validatePassword(String) [DELETED]
     ⚠️ 严重性: CRITICAL - 此方法已被删除，所有调用方将面临编译失败
     📞 直接调用方 (3个):
        - AuthController.login(String, String) @ AuthController.java:45 [COMPILE_ERROR]
        - AdminService.resetPassword(Long) @ AdminService.java:112 [COMPILE_ERROR]
        - OAuthService.authenticate(String) @ OAuthService.java:78 [COMPILE_ERROR]
     🎯 影响入口点 (2个):
        - AuthController.login [HTTP_API] - POST /auth/login
        - OAuthService.authenticate [HTTP_API] - POST /oauth/token
```

---

## 三、CHA (类层次分析) 修复与增强 (P1)

### 3.1 问题诊断

v3.1 中 `enable_cha=True` 但未生效，根因为 `ClassHierarchyIndex` 构建失败：

1. 接口解析时未正确提取 `implements` 信息
2. 实现类映射建立时机过早（基线数据未完全写入）
3. 调用链构建时未正确传递 `class_hierarchy` 实例
4. **v3.2 新增**：全限定名解析存在笛卡尔积式匹配风险，大型项目中可能导致内存与性能瓶颈

### 3.2 技术实现

#### 3.2.1 类层次索引构建修复（优化版）

修改 `class_hierarchy.py`，采用短名映射索引替代 O(n²) 遍历：

```python
class ClassHierarchyIndex:
    """修复后的类层次分析索引（内存优化版）"""
    
    def __init__(self, db_helper, project_id: int):
        self.db = db_helper
        self.project_id = project_id
        self.interface_map = {}      # interface -> [impl_classes]
        self.class_ancestors = {}    # class -> [ancestors]
        self._short_name_index = {}  # short_name -> [full_name, ...]  # 新增
        self._build_index()
        
    def _build_index(self):
        """构建类层次索引（修复版 + 内存优化）"""
        # 1. 提取所有接口定义，并构建短名索引
        interfaces = self.db.query(
            "SELECT class_name, package_name, filepath "
            "FROM class "
            "WHERE class_type = 'interface' AND project_id = ?",
            (self.project_id,)
        )
        
        for iface in interfaces:
            full_name = f"{iface['package_name']}.{iface['class_name']}"
            self.interface_map[full_name] = []
            # 构建短名映射索引
            short_name = iface['class_name']
            if short_name not in self._short_name_index:
                self._short_name_index[short_name] = []
            self._short_name_index[short_name].append(full_name)
        
        # 2. 提取所有实现类（修复：正确解析 implements 字段）
        classes = self.db.query(
            "SELECT class_name, package_name, implements, extends_class "
            "FROM class "
            "WHERE project_id = ? AND (implements IS NOT NULL OR extends_class IS NOT NULL)",
            (self.project_id,)
        )
        
        for cls in classes:
            full_name = f"{cls['package_name']}.{cls['class_name']}"
            
            # 解析 implements（支持多接口，逗号分隔）
            if cls['implements']:
                implemented = [i.strip() for i in cls['implements'].split(',')]
                for iface_short in implemented:
                    # 使用短名索引加速解析（O(1) 替代 O(n)）
                    iface_full = self._resolve_interface_name_optimized(
                        iface_short, cls['package_name']
                    )
                    if iface_full in self.interface_map:
                        self.interface_map[iface_full].append({
                            'class': full_name,
                            'type': 'IMPLEMENTS'
                        })
            
            # 解析 extends
            if cls['extends_class']:
                parent = self._resolve_class_name(cls['extends_class'], cls['package_name'])
                self.class_ancestors[full_name] = parent
    
    def _resolve_interface_name_optimized(self, iface_short: str, current_package: str) -> str:
        """通过短名索引和包名精确定位接口（避免模糊匹配）"""
        candidates = self._short_name_index.get(iface_short, [])
        
        if len(candidates) == 1:
            return candidates[0]
        
        # 优先匹配同包
        for c in candidates:
            if c.startswith(current_package):
                return c
        
        # 通过 import 语句解析（如需）
        return self._resolve_by_import(candidates)
    
    def resolve_interface_call(self, callee_package_class: str, callee_signature: str) -> List[Dict]:
        """解析接口调用到实现类方法"""
        if callee_package_class not in self.interface_map:
            return []
        
        implementations = []
        for impl in self.interface_map[callee_package_class]:
            impl_key = f"{impl['class']}|{callee_signature}"
            implementations.append({
                'key': impl_key,
                'class': impl['class'],
                'signature': callee_signature,
                'type': 'CHA_RESOLVED'
            })
        
        return implementations
```

#### 3.2.2 调用链构建器集成修复

修改 `analyzer.py` 中的 `build_call_chains_for_changes`：

```python
def build_call_chains_for_changes(username, git_url, commit_old, commit_new, 
                                  changed_methods, max_depth=5, enable_cha=True):
    """修复 CHA 传递问题"""
    
    # 1. 构建统一方法索引（修复：确保包含基线和增量）
    unified_index = UnifiedMethodIndex(db_helper, project_id=0)  # 基线
    unified_index.merge_project(project_id=1)  # 增量
    
    # 2. 构建类层次索引（修复：延迟构建，确保数据完整）
    class_hierarchy = None
    if enable_cha:
        try:
            class_hierarchy = ClassHierarchyIndex(db_helper, project_id=0)
            logger.info(f"类层次分析 (CHA): 已启用，索引大小: {len(class_hierarchy.interface_map)}")
        except Exception as e:
            logger.warning(f"类层次分析 (CHA): 初始化失败 - {e}")
    
    # 3. 构建反向调用索引（修复：正确传递 class_hierarchy）
    reverse_index = ReverseCallerIndex(unified_index, class_hierarchy=class_hierarchy)
    
    # 4. 构建向上调用链
    upwards_builder = UpwardsCallChainBuilder(
        reverse_index, 
        entry_detector=AnnotationAwareEntryDetector(),
        max_depth=max_depth
    )
    
    # ... 后续逻辑
```

#### 3.2.3 反向索引 CHA 支持

修改 `upwards_builder.py` 中的 `ReverseCallerIndex`：

```python
class ReverseCallerIndex:
    def __init__(self, unified_index, class_hierarchy=None):
        self.unified_index = unified_index
        self.class_hierarchy = class_hierarchy
        self.reverse_map = {}
        self._build_reverse_index()
    
    def _build_reverse_index(self):
        """构建反向索引（支持 CHA）"""
        for key, methods in self.unified_index._unified_index.items():
            for method in methods:
                invocation_map = method.get('method_invocation_map', '{}')
                callable_points = InvocationPointParser.parse(invocation_map)
                
                for point in callable_points:
                    callee_key = f"{point['package_class']}|{point['signature']}"
                    self._add_caller(callee_key, caller_info, point['lines'])
                    
                    # 如果是接口调用，添加实现类映射
                    if self.class_hierarchy:
                        impl_methods = self.class_hierarchy.resolve_interface_call(
                            point['package_class'], 
                            point['signature']
                        )
                        for impl in impl_methods:
                            self._add_caller(
                                impl['key'], 
                                caller_info, 
                                point['lines'],
                                call_type='CHA_RESOLVED'
                            )
```

#### 3.2.4 method_invocation_map 契约定义（新增）

为确保调用链分析的准确性，明确定义 `method_invocation_map` 字段规范：

```python
"""
method_invocation_map 字段规范:
- 生成时机: JavaParse.analyze() 执行时，通过 AST 解析类体内的所有方法调用
- 存储格式: JSON
  {
    "invocations": [
      {
        "callee_class": "com.example.UserService",      # 全限定名（如果可解析）
        "callee_short": "UserService",                   # 短名（仅从代码中提取到时）
        "callee_method": "delete",
        "callee_signature": "delete(Long)",
        "call_line": 45,
        "caller_context": "LOCAL_VARIABLE"               # 调用上下文
      }
    ]
  }
- 限制: 
  - 仅能解析同项目内的显式调用
  - 反射调用、依赖注入调用（@Autowired）无法识别
  - 接口方法的实现类调用需 CHA 补充
"""
```

### 3.3 验证输出

```
类层次分析 (CHA): 已启用，索引大小: 24
接口映射示例:
  - com.macro.mall.service.OmsOrderService -> [OmsOrderServiceImpl, OmsPortalOrderServiceImpl]
  - com.macro.mall.service.UmsAdminService -> [UmsAdminServiceImpl]

调用链追踪示例:
  OrderController.createOrder (MODIFIED)
    --> OrderService.createOrder (接口调用，CHA_RESOLVED)
      --> OrderServiceImpl.createOrder (MODIFIED)  [通过CHA解析]
        --> OrderMapper.insert (UNCHANGED)
```

---

## 四、字段级变更分析 (P2)

### 4.1 数据库表扩展

扩展 `field` 表，增加变更追踪支持，并新增字段访问记录表：

```sql
-- 字段表增强
ALTER TABLE field ADD COLUMN change_type TEXT DEFAULT 'UNCHANGED';
ALTER TABLE field ADD COLUMN old_value TEXT;
ALTER TABLE field ADD COLUMN new_value TEXT;
ALTER TABLE field ADD COLUMN impact_methods TEXT; -- JSON，记录引用该字段的方法

-- 新增字段影响关联表
CREATE TABLE field_impact (
    impact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id INTEGER NOT NULL,
    method_id INTEGER NOT NULL,
    impact_type TEXT NOT NULL, -- 'READ', 'WRITE', 'BOTH'
    project_id INTEGER NOT NULL,
    FOREIGN KEY (field_id) REFERENCES field(field_id),
    FOREIGN KEY (method_id) REFERENCES methods(method_id)
);

-- 新增字段访问记录表（支持 AST 精确分析）
CREATE TABLE method_field_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    access_type TEXT NOT NULL,  -- 'READ', 'WRITE', 'METHOD_CALL'
    line_number INTEGER,
    project_id INTEGER NOT NULL,
    FOREIGN KEY (method_id) REFERENCES methods(method_id)
);

CREATE INDEX idx_mfa_method ON method_field_access(method_id);
CREATE INDEX idx_mfa_field ON method_field_access(field_name);
```

### 4.2 字段变更标记实现（两阶段分析）

实现 `change_type_analyzer.py` 中的 `_mark_field_changes`，采用 AST 精确匹配 + 文本搜索验证的两阶段策略：

```python
def _mark_field_changes(self, diff_parse_map, project_id, commit_new, commit_old):
    """标记字段级变更（完整实现，两阶段分析）"""
    for filepath, diff_info in diff_parse_map.items():
        added_lines = set(diff_info.get('line_num_added', []))
        removed_lines = set(diff_info.get('line_num_removed', []))
        
        # 查询该文件的所有字段
        fields = self.db.query(
            "SELECT f.field_id, f.field_name, f.field_type, f.annotations, "
            "f.start_line, f.end_line, f.class_id, c.class_name "
            "FROM field f JOIN class c ON f.class_id = c.class_id "
            "WHERE c.filepath LIKE ? AND f.project_id = ?",
            (f'%{filepath}', project_id)
        )
        
        for field in fields:
            field_lines = set(range(field['start_line'], field['end_line'] + 1))
            
            # 判断变更类型
            if field_lines.issubset(removed_lines):
                change_type = 'DELETED'
            elif field_lines & added_lines:
                # 字段行与新增行有交集 → 字段被修改（类型、注解、初始化值变化）
                change_type = 'MODIFIED'
            else:
                continue
            
            # 更新字段变更类型
            self.db.execute(
                "UPDATE field SET change_type = ? WHERE field_id = ?",
                (change_type, field['field_id'])
            )
            
            # 分析字段影响：使用两阶段分析
            self._analyze_field_impact(field, change_type, project_id)
            
def _analyze_field_impact(self, field, change_type, project_id):
    """分析字段变更对方法的影响（两阶段分析：AST + 文本搜索验证）"""
    
    # 阶段1: 精确匹配 - 通过 AST 分析字段引用
    referencing_methods = self._find_field_references_by_ast(
        field['class_id'], field['field_name'], project_id
    )
    
    # 阶段2: 补充搜索 - DTO/Entity 的反射映射
    if field['annotations'] and any(
        a in field['annotations'] for a in ['@ApiModelProperty', '@TableField', '@Column']
    ):
        # 字段被序列化框架使用，标记所有使用该类的方法
        class_users = self._find_class_users(field['class_id'], project_id)
        referencing_methods.extend(class_users)
    
    impacted_methods = []
    for method in referencing_methods:
        impacted_methods.append({
            'method_id': method['method_id'],
            'method_name': method['method_name'],
            'impact_type': 'FIELD_DEPENDENT'
        })
        
        # 记录影响关系
        self.db.execute(
            "INSERT INTO field_impact (field_id, method_id, impact_type, project_id) "
            "VALUES (?, ?, ?, ?)",
            (field['field_id'], method['method_id'], 'READ', project_id)
        )
    
    # 更新字段影响记录
    self.db.execute(
        "UPDATE field SET impact_methods = ? WHERE field_id = ?",
        (json.dumps(impacted_methods), field['field_id'])
    )

def _find_field_references_by_ast(self, class_id, field_name, project_id):
    """
    通过 AST 精确查找字段引用
    
    实现: 在 JavaParse 中增加字段访问记录
    - 在解析方法体时，记录所有 MemberReference 和 FieldAccess 节点
    - 存储到 method_field_access_map 字段（新增）
    """
    return self.db.query(
        "SELECT m.method_id, m.method_name, m.class_id "
        "FROM methods m "
        "JOIN method_field_access mfa ON m.method_id = mfa.method_id "
        "WHERE mfa.field_name = ? AND m.project_id = ? AND m.class_id = ?",
        (field_name, project_id, class_id)
    )
```

### 4.3 字段影响在调用链中的展示

在 `CallChainNode` 中增加字段影响信息：

```python
class CallChainNode:
    def __init__(self, ...):
        # ... 原有属性
        self.field_impacts = []  # 新增：字段影响列表
        
    def add_field_impact(self, field_name, change_type, impact_methods):
        self.field_impacts.append({
            'field_name': field_name,
            'change_type': change_type,
            'affected_methods': impact_methods
        })
```

### 4.4 输出示例

```
字段级变更影响:
  📦 Class: UserDTO
    📝 Field: phoneNumber [MODIFIED] (String → String, 注解变更)
      🔗 影响方法 (3个):
        - UserController.updateUser [MODIFIED] - 写入字段
        - UserService.validatePhone [UNCHANGED] - 读取字段（需关注）
        - UserMapper.updateById [UNCHANGED] - 通过反射映射（运行时风险）
```

---

## 五、MyBatis Mapper 链路追踪 (P4)

### 5.1 Mapper 解析器增强（XML 解析器替代正则）

增强 `mapper_parse.py`，使用 `xml.etree.ElementTree` 替代正则解析，避免嵌套标签截断问题：

```python
import xml.etree.ElementTree as ET

class MyBatisMapperParser:
    """增强版 MyBatis Mapper 解析器（XML 解析器版）"""
    
    def __init__(self):
        self.sql_tags = ['select', 'insert', 'update', 'delete']
    
    def parse_mapper_file(self, xml_content: str, namespace: str) -> List[Dict]:
        """
        解析 Mapper XML，提取 SQL 语句与方法映射（使用 XML 解析器）
        
        Returns:
            [
                {
                    'id': 'selectById',
                    'sql_type': 'SELECT',
                    'parameter_type': 'Long',
                    'result_type': 'User',
                    'sql_content': 'SELECT * FROM user WHERE id = #{id}',
                    'tables': ['user'],
                    'full_method': 'com.example.mapper.UserMapper.selectById'
                }
            ]
        """
        root = ET.fromstring(xml_content)
        namespace = root.get('namespace', namespace)
        
        results = []
        
        for tag_name in self.sql_tags:
            for element in root.findall(f'.//{tag_name}'):
                sql_id = element.get('id')
                if not sql_id:
                    continue
                
                # 安全提取 SQL 内容（包含嵌套标签，如 <foreach>）
                sql_fragment = ET.tostring(element, encoding='unicode')
                
                # 提取表名
                tables = self._extract_tables_from_element(element)
                
                results.append({
                    'id': sql_id,
                    'sql_type': tag_name.upper(),
                    'namespace': namespace,
                    'full_method': f"{namespace}.{sql_id}",
                    'parameter_type': element.get('parameterType'),
                    'result_type': element.get('resultType', element.get('resultMap')),
                    'sql_content': self._extract_sql(sql_fragment),
                    'tables': tables,
                    'xml_fragment': sql_fragment
                })
        
        return results
    
    def _extract_tables_from_element(self, element) -> List[str]:
        """从 XML 元素中提取表名"""
        sql_text = ET.tostring(element, encoding='unicode')
        tables = re.findall(
            r'(?:FROM|INTO|UPDATE|JOIN)\s+`?(\w+)`?', 
            sql_text, 
            re.IGNORECASE
        )
        return list(set(tables))
```

### 5.2 Mapper 方法索引

新增 `mapper_index.py`，建立 Mapper 方法与 Java 方法的关联：

```python
class MapperMethodIndex:
    """Mapper 方法索引，关联 XML SQL 与 Java Mapper 接口"""
    
    def __init__(self, db_helper):
        self.db = db_helper
        self.mapper_map = {}  # full_method -> mapper_info
        
    def build_index(self, project_id: int):
        """构建 Mapper 方法索引"""
        # 1. 查询所有 Mapper XML 文件解析结果
        mapper_methods = self.db.query(
            "SELECT * FROM mapper_methods WHERE project_id = ?", 
            (project_id,)
        )
        
        for mm in mapper_methods:
            self.mapper_map[mm['full_method']] = mm
        
        # 2. 关联 Java Mapper 接口方法
        java_mappers = self.db.query(
            "SELECT m.method_id, m.method_name, c.class_name, c.package_name "
            "FROM methods m JOIN class c ON m.class_id = c.class_id "
            "WHERE c.class_name LIKE '%Mapper' AND m.project_id = ?",
            (project_id,)
        )
        
        for jm in java_mappers:
            full_method = f"{jm['package_name']}.{jm['class_name']}.{jm['method_name']}"
            if full_method in self.mapper_map:
                self.mapper_map[full_method]['java_method_id'] = jm['method_id']
    
    def get_sql_by_java_method(self, package_class: str, method_name: str) -> Optional[Dict]:
        """通过 Java 方法名获取对应 SQL"""
        full_method = f"{package_class}.{method_name}"
        return self.mapper_map.get(full_method)
```

### 5.3 向下调用链 DAO 层扩展

修改 `downwards_builder.py`，支持 Mapper 链路：

```python
class DownwardsCallChainBuilder(CallChainBuilder):
    """增强版向下调用链构建器，支持 MyBatis 链路"""
    
    def __init__(self, unified_index, mapper_index=None):
        super().__init__(unified_index)
        self.mapper_index = mapper_index
        
    def expand_node(self, node: CallChainNode, current_depth: int):
        """扩展节点，增加 Mapper/SQL 层"""
        # 1. 原有逻辑：展开普通方法调用
        super().expand_node(node, current_depth)
        
        # 2. 新增：如果是 Service 层调用 Mapper 方法，展开 SQL 详情
        if self.mapper_index and self._is_mapper_call(node):
            sql_info = self.mapper_index.get_sql_by_java_method(
                node.package_class, 
                node.method_name
            )
            if sql_info:
                sql_node = CallChainNode(
                    name=f"SQL:{sql_info['sql_type']}",
                    package_class=sql_info['tables'][0] if sql_info['tables'] else 'UNKNOWN',
                    method_signature=sql_info['sql_content'][:50] + '...',
                    node_type='SQL',
                    change_type='UNCHANGED',
                    invocation_lines=[]
                )
                sql_node.sql_details = sql_info
                node.children.append(sql_node)
    
    def _is_mapper_call(self, node: CallChainNode) -> bool:
        """判断是否为 Mapper 层调用"""
        return 'Mapper' in node.package_class or node.package_class.endswith('Dao')
```

### 5.4 输出示例

```
向下调用链 (增强版):
  UserService.updateUser (MODIFIED)
    --> UserMapper.updateById (UNCHANGED)
      --> SQL:UPDATE [表: user]
        SQL: UPDATE user SET phone_number = #{phoneNumber}, updated_at = now() WHERE id = #{id}
        📝 影响表: user
        🔍 操作类型: UPDATE
        ⚠️ 风险: 字段 phone_number 被修改，需确认索引影响
    --> RedisTemplate.delete (UNCHANGED)
      --> [第三方库，终止展开]
```

---

## 六、方法签名严格匹配 (P3)

### 6.1 跨版本方法匹配增强

修改 `change_type_analyzer.py` 中的跨版本匹配逻辑：

```python
def _mark_added_modified_methods(self, filepath, project_id, commit_new, commit_old):
    """增强版跨版本方法匹配，支持签名一致性校验"""
    
    # 查询增量版本中的方法
    new_methods = self.db.query(
        "SELECT m.method_id, m.method_name, m.parameters, m.return_type, "
        "m.start_line, m.end_line, m.class_id "
        "FROM methods m JOIN class c ON m.class_id = c.class_id "
        "WHERE c.filepath LIKE ? AND m.project_id = ?",
        (f'%{filepath}', project_id)
    )
    
    for new_method in new_methods:
        # 构建参数签名
        new_signature = self._build_param_signature(new_method['parameters'])
        
        # 在基线中查找候选方法（同文件、同名）
        old_methods = self.db.query(
            "SELECT m.method_id, m.parameters, m.return_type "
            "FROM methods m JOIN class c ON m.class_id = c.class_id "
            "WHERE c.filepath LIKE ? AND m.method_name = ? AND m.project_id = 0",
            (f'%{filepath}', new_method['method_name'])
        )
        
        matched = False
        for old_method in old_methods:
            old_signature = self._build_param_signature(old_method['parameters'])
            
            if old_signature == new_signature:
                # 签名完全匹配 → MODIFIED
                self.db.execute(
                    "UPDATE methods SET change_type = 'MODIFIED', matched_method_id = ? "
                    "WHERE method_id = ?",
                    (old_method['method_id'], new_method['method_id'])
                )
                matched = True
                break
            else:
                # 同名但签名不同 → 可能是重载方法变更
                continue
        
        if not matched:
            # 未找到匹配 → ADDED（或重载新增）
            self.db.execute(
                "UPDATE methods SET change_type = 'ADDED' WHERE method_id = ?",
                (new_method['method_id'],)
            )
            
            # 检查是否为重载替换：基线中有同名但不同签名的方法被删除
            self._check_overload_replacement(new_method, old_methods, filepath)

def _build_param_signature(self, parameters_json: str) -> str:
    """构建参数签名，用于严格匹配"""
    try:
        params = json.loads(parameters_json) if parameters_json else []
        return ','.join([
            f"{p.get('parameter_type', 'Object')}" 
            for p in params
        ])
    except:
        return ''
```

### 6.2 重载方法处理（增强版，支持多对一合并）

```python
def _check_overload_replacement(self, new_method, old_methods, filepath):
    """检查是否为重载方法替换场景（支持多对一合并）"""
    matched_old = []
    
    for old in old_methods:
        # 如果基线方法被标记为 DELETED，且与新增方法同名不同参
        old_deleted = self.db.query_one(
            "SELECT change_type FROM methods WHERE method_id = ?",
            (old['method_id'],)
        )
        
        if old_deleted and old_deleted['change_type'] == 'DELETED':
            matched_old.append(old)
    
    if not matched_old:
        return None
    
    # 多对一场景：删除 N 个重载方法，新增 1 个统一方法
    if len(matched_old) > 1:
        logger.warning(
            f"检测到重载方法合并: {filepath}\n"
            f"  旧方法 ({len(matched_old)}个): {[m['parameters'] for m in matched_old]}\n"
            f"  新方法 (1个): {new_method['parameters']}"
        )
        
        self.db.execute(
            "UPDATE methods SET change_type = 'ADDED_OVERLOAD_MERGE', "
            "replaced_method_ids = ? WHERE method_id = ?",
            (json.dumps([m['method_id'] for m in matched_old]), new_method['method_id'])
        )
    else:
        # 一对一替换
        self.db.execute(
            "UPDATE methods SET change_type = 'ADDED_OVERLOAD', "
            "replaced_method_id = ? WHERE method_id = ?",
            (matched_old[0]['method_id'], new_method['method_id'])
        )
    
    return {
        'type': 'MANY_TO_ONE' if len(matched_old) > 1 else 'ONE_TO_ONE',
        'replaced': [m['method_id'] for m in matched_old]
    }
```

---

## 七、Commit 范围显示修复 (P5)

### 7.1 元数据传递修复

修改 `analyzer.py` 中的调用链构建入口：

```python
def build_call_chains_for_changes(username, git_url, commit_old, commit_new, 
                                  changed_methods, max_depth=5, enable_cha=True):
    """修复 Commit 范围传递"""
    
    # 标准化 commit 标识符
    commit_old_short = extract_short_tag(commit_old)
    commit_new_short = extract_short_tag(commit_new)
    
    result = {
        "metadata": {
            "username": username,
            "git_url": git_url,
            "baseline_commit": commit_old_short,  # 修复：确保传递短标识符
            "target_commit": commit_new_short,
            "commit_range": f"{commit_old_short}..{commit_new_short}",  # 新增
            "analysis_time": datetime.now().isoformat(),
            "max_depth": max_depth,
            "cha_enabled": enable_cha
        },
        "upwards": upwards_result,
        "downwards": downwards_result
    }
    
    return result
```

### 7.2 文本输出修复

修改 `visualizer.py`：

```python
def format_upwards_chains(chains, metadata):
    """修复文本输出中的 Commit 显示"""
    lines = [
        f"JCCI 向上调用链分析 (影响面)",
        f"================================",
        f"项目: {metadata.get('git_url', 'N/A')}",
        f"Commit范围: {metadata.get('commit_range', 'N/A')}",  # 修复：使用 commit_range
        f"基线: {metadata.get('baseline_commit', 'N/A')}",
        f"目标: {metadata.get('target_commit', 'N/A')}",
        f"分析时间: {metadata.get('analysis_time', 'N/A')}",
        f""
    ]
    # ... 后续逻辑
```

---

## 八、v3.2 完整架构更新

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户交互层                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ workflow1.py │    │ 命令行工具   │    │  Streamlit   │      │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘      │
└─────────┼──────────────────┼──────────────────┼────────────────┘
          │                  │                  │
          ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                     核心分析引擎层 (v3.2)                         │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  1. Git Diff 解析模块 (diff_parse.py)                     │  │
│  │     • 支持 .java / .xml / .properties 文件               │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  2. 变更类型分析模块 (change_type_analyzer.py)             │  │
│  │     • 文件级: ADDED/MODIFIED/DELETED                      │  │
│  │     • 类级: 标记 class 表 change_type                    │  │
│  │     • 方法级: 跨版本签名匹配 (新增重载处理)               │  │
│  │     • 字段级: 新增 ADDED/MODIFIED/DELETED 标记 ⭐         │  │
│  │     • 事务边界: 显式 begin/commit/rollback               │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  3. 双向调用链分析模块 (call_chain/)                        │  │
│  │     • 向上分析: ReverseCallerIndex + CHA (修复) ⭐        │  │
│  │       - 支持接口多态调用解析                              │  │
│  │       - 短名映射索引优化（避免 O(n²)）                    │  │
│  │       - EntryDetector: HTTP_API/SCHEDULED_TASK/...        │  │
│  │       - 新增 DeletedMethodImpactAnalyzer ⭐               │  │
│  │     • 向下分析: DownwardsCallChainBuilder                 │  │
│  │       - 新增 MapperMethodIndex (MyBatis SQL 链路) ⭐      │  │
│  │       - XML 解析器替代正则（避免嵌套标签截断）            │  │
│  │       - 支持 SQL 语句级影响展示                           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  4. 基线增量分析模块 (analyze.py)                          │  │
│  │     • 场景 A/B/C 支持                                     │  │
│  │     • JSON 缓存机制（v3.1 → v3.2 兼容）                   │  │
│  │     • 修复 Commit 范围传递 ⭐                              │  │
│  │     • 强制同步点：标记完成后 commit 再构建索引              │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                     数据存储层                                   │
│                                                                 │
│  ┌──────────────────┐    ┌──────────────────┐                  │
│  │  SQLite 数据库    │    │  JSON 缓存文件   │                  │
│  │                  │    │                  │                  │
│  │ • project 表     │    │ • analysis_      │                  │
│  │ • class 表       │    │   result.json    │                  │
│  │ • methods 表     │    │ • upwards.txt    │                  │
│  │ • field 表 (增强)│    │ • downwards.txt  │                  │
│  │ • field_impact 表│   │ • call_chains.json│                 │
│  │ • mapper_methods │    │ • deleted_       │                  │
│  │   表 (新增)      │    │   impact.json ⭐  │                  │
│  │ • method_field_  │    │ • field_impacts_ │                  │
│  │   access 表(新增)│    │   cache.json ⭐   │                  │
│  └──────────────────┘    └──────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 九、v3.2 目标达成度预期

| 维度 | v3.1 达成度 | v3.2 预期 | 提升说明 |
|------|-------------|-----------|----------|
| Git Diff 解析 | 95% | 95% | 保持稳定 |
| 变更内容识别 | 90% | **95%** | 新增字段级分析 |
| 变更类型标记 | 85% | **95%** | 严格签名匹配 + 重载处理 |
| 向上调用链分析 | 90% | **97%** | CHA 修复 + 删除方法影响分析 |
| 向下调用链分析 | 95% | **98%** | MyBatis SQL 链路追踪 |
| 结果可视化 | 85% | 90% | 修复 Commit 显示，增强文本输出 |
| 基线复用机制 | 95% | 95% | 保持稳定 |
| 数据一致性 | 80% | **95%** | 事务边界 + 同步点 + 缓存兼容 |

**综合预期评分**: **87% → 95%**

---

## 十、迁移指南

### 从 v3.1 升级到 v3.2

1. **数据库迁移**:
   ```bash
   python scripts/migrate_v3_1_to_v3_2.py --db_path /path/to/baseline.db
   ```

2. **配置更新**:
   ```python
   # config.py 新增配置
   ENABLE_FIELD_ANALYSIS = True
   ENABLE_MAPPER_ANALYSIS = True
   ENABLE_CHA = True  # 现在真正生效
   ```

3. **API 兼容性**:
   - `build_call_chains_for_changes()` 新增可选参数 `enable_field_analysis=True`
   - 返回结果新增 `field_impacts` 和 `deleted_impacts` 字段

4. **缓存兼容性处理（新增）**:
   ```python
   def _load_analysis_cache(self) -> dict:
       cache = super()._load_analysis_cache()
       if cache:
           # v3.2 向后兼容：补充缺失字段
           if 'field_impacts' not in cache:
               cache['field_impacts'] = []
               logger.info("v3.1 缓存文件，field_impacts 补充为空")
           if 'deleted_impacts' not in cache:
               cache['deleted_impacts'] = []
           if 'mapper_chains' not in cache:
               cache['mapper_chains'] = []
       return cache
   ```

5. **事务边界使用示例**:
   ```python
   def analyze_two_commit_incremental(self, ...):
       try:
           self.db.begin_transaction()  # 显式开启事务
           
           # 1. 标记变更
           self.change_type_analyzer.analyze_and_mark_changes(...)
           
           # 2. 字段影响分析
           self.change_type_analyzer.analyze_field_impacts(...)
           
           # 3. 删除方法影响
           self.deleted_analyzer.mark_impacts(...)
           
           self.db.commit()  # 原子提交
       except Exception as e:
           self.db.rollback()
           logger.error(f"分析失败，已回滚: {e}")
           raise
   ```

---

**文档版本**: v3.2.1  
**最后更新**: 2026-05-11