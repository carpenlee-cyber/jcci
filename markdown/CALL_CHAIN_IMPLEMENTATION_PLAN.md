# JCCI 调用链路分析器 - 实现规划文档

> **版本**: v1.0  
> **日期**: 2026-05-05  
> **策略**: TDD（测试驱动开发）  
> **目标**: 基于基线+增量合并数据，构建准确的 commit_new 版本调用链路

---

## 一、项目背景与目标

### 1.1 业务需求

在 JCCI 完成两个 commit 的增量分析后，需要进一步分析**变更方法的调用链路**，以便：
1. 理解变更影响的完整传播路径
2. 识别潜在的回归风险点
3. 生成带顺序的影响分析报告

### 1.2 技术挑战

**核心问题**：commit_new 版本的代码 = 基线代码 + 变更部分

如果只查询增量数据（project_id=1），会发现大量未变更的方法不存在，导致**调用链断裂**。

**解决方案**：构建统一索引，自动合并基线和增量数据：
- 优先从增量（project_id=1）查询
- 如果不存在，从基线（project_id=0）查询
- 删除的方法自动排除

### 1.3 实现目标

✅ **功能目标**：
- 支持从任意方法开始构建完整调用链
- 自动处理基线+增量数据合并
- 精确的重载方法匹配（基于参数类型）
- 环检测和深度限制
- 调用点按行号排序

✅ **性能目标**：
- Mall 项目（14000+ 方法）索引构建 < 5 秒
- 单个调用链构建 < 1 秒
- 内存占用 < 50 MB

✅ **质量目标**：
- 单元测试覆盖率 ≥ 90%
- 所有边界场景有测试覆盖
- 在真实 Mall 项目上验证通过

---

## 二、架构设计

### 2.1 模块划分

```
src/jcci/call_chain/
├── __init__.py              # 包初始化，导出公共接口
├── index.py                 # UnifiedMethodIndex - 统一方法索引
├── parser.py                # InvocationPointParser - 调用点解析器
├── builder.py               # CallChainBuilder - 调用链构建器
└── models.py                # CallChainNode - 数据模型

tests/test_call_chain/
├── __init__.py
├── test_unified_index.py    # 索引测试
├── test_parser.py           # 解析器测试
├── test_builder.py          # 构建器测试
├── test_integration.py      # 集成测试
└── test_e2e.py              # 端到端测试
```

### 2.2 核心类关系图

```
┌─────────────────────────┐
│   CallChainAnalyzer     │  ← 对外统一接口（可选，初期可直接用 Builder）
│  (analyze.py 中集成)     │
└────────────┬────────────┘
             │ uses
             ▼
┌─────────────────────────┐
│  CallChainBuilder       │  ← 核心构建逻辑（DFS 递归）
│  - build()              │
│  - _dfs_expand()        │
└────────────┬────────────┘
             │ uses
             ▼
┌─────────────────────────┐
│  UnifiedMethodIndex     │  ← 数据访问层（批量预加载 + 合并）
│  - query_method()       │
│  - build()              │
└────────────┬────────────┘
             │ uses
             ▼
┌─────────────────────────┐
│ InvocationPointParser   │  ← 工具类（JSON 解析）
│  - parse()              │
└─────────────────────────┘
```

### 2.3 数据流

```
输入: (package_class, method_signature, project_id, commit_old, commit_new)
    │
    ▼
┌──────────────────────────────┐
│ Step 1: 构建统一索引          │
│ - 加载基线 (project_id=0)    │
│ - 加载增量 (project_id=1)    │
│ - 合并：增量覆盖基线          │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Step 2: 查找起始方法          │
│ - 从统一索引查询              │
│ - 解析 method_invocation_map │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Step 3: 提取并排序调用点      │
│ - 解析 JSON                  │
│ - 按行号升序排列              │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Step 4: DFS 递归构建         │
│ - 对每个调用点：              │
│   a. 环检测                  │
│   b. 创建子节点              │
│   c. 递归下探                │
│   d. 回溯                    │
└──────────────┬───────────────┘
               │
               ▼
输出: CallChainNode 树结构
```

---

## 三、详细设计

### 3.1 数据模型（models.py）

```python
@dataclass
class CallChainNode:
    """调用链路节点"""
    node_id: str                          # 唯一标识: "{depth}|{package_class}|{method_signature}"
    package_class: str                    # 完整类名: "com.macro.mall.service.UmsMenuService"
    method_signature: str                 # 方法签名: "list(int,int)"
    method_name: str                      # 方法名: "list"
    class_name: str                       # 类名: "UmsMenuService"
    depth: int = 0                        # 深度（根节点为 0）
    invocation_lines: List[int] = field(default_factory=list)  # 调用发生的行号
    children: List['CallChainNode'] = field(default_factory=list)
    is_cyclic: bool = False               # 是否检测到环
    is_leaf: bool = False                 # 是否为叶子节点
    db_method_id: Optional[int] = None    # 数据库中的 method_id
    
    def to_dict(self) -> dict:
        """转换为字典（用于 JSON 序列化）"""
        return {
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
            "children": [child.to_dict() for child in self.children]
        }
```

**设计决策**：
- ✅ 简化模型：只保留必要字段
- ❌ 移除 `call_type`：当前只处理方法调用
- ❌ 移除 `is_duplicate`：首期不实现全局 visited
- ❌ 移除 `entity_references`：当前数据中没有 entity
- ❌ 移除 `error`：简单场景不需要复杂错误挂载

---

### 3.2 统一方法索引（index.py）

#### 3.2.1 核心职责

1. **批量预加载**：一次性加载基线和增量的所有方法到内存
2. **版本合并**：增量覆盖基线，过滤删除的方法
3. **快速查询**：支持精确重载匹配

#### 3.2.2 关键算法

```python
def _build_unified_index(self):
    """
    构建统一索引：增量覆盖基线
    
    规则：
    1. 先复制所有基线方法（排除 DELETED）
    2. 用增量方法覆盖/添加
    """
    self._unified_index = {}
    
    # Step 1: 复制基线方法（过滤删除的）
    for key, methods in self.baseline_index.items():
        active_methods = [
            m for m in methods 
            if m.get('change_type') != 'DELETED'
        ]
        if active_methods:
            self._unified_index[key] = active_methods
    
    # Step 2: 用增量覆盖
    for key, methods in self.incremental_index.items():
        self._unified_index[key] = methods  # 直接覆盖
```

#### 3.2.3 重载匹配逻辑

```python
def query_method(self, package_class, method_signature):
    """
    查询方法（支持精确重载匹配）
    
    匹配策略：
    1. 提取目标签名的参数类型列表
    2. 与候选方法的 parameters JSON 比对
    3. 完全匹配 → 返回
    4. 无匹配 → 返回第一个（记录告警）
    """
    method_name = method_signature.split('(')[0]
    key = (package_class, method_name)
    
    candidates = self._unified_index.get(key, [])
    if not candidates:
        return None
    
    # 精确重载匹配
    target_params = self._extract_param_types(method_signature)
    
    for candidate in candidates:
        try:
            params = json.loads(candidate['parameters'])
            candidate_types = [p['parameter_type'] for p in params]
            if candidate_types == target_params:
                return candidate
        except:
            continue
    
    # 无精确匹配，返回第一个
    logging.warning(f"No exact overload match for {method_signature}, using first candidate")
    return candidates[0]
```

**设计决策**：
- ✅ 批量预加载：避免 N+1 SQL 查询
- ✅ 内存索引：Mall 项目约 28MB（可接受）
- ✅ 精确重载匹配：核心价值，必须保证准确性
- ❌ 不实现模糊匹配：增加复杂度，收益低

---

### 3.3 调用点解析器（parser.py）

#### 3.3.1 核心职责

从 `method_invocation_map` JSON 中提取结构化的调用点列表。

#### 3.3.2 实现逻辑

```python
@staticmethod
def parse(invocation_map_json: str) -> List[dict]:
    """
    解析 method_invocation_map
    
    Returns:
        List[dict]: [
            {
                'package_class': 'com.xxx.Service',
                'signature': 'method(int,String)',
                'lines': [34, 35]
            },
            ...
        ]
    """
    if not invocation_map_json:
        return []
    
    try:
        invocation_map = json.loads(invocation_map_json)
    except json.JSONDecodeError:
        logging.error(f"Failed to parse invocation map: {invocation_map_json[:100]}")
        return []
    
    points = []
    
    for package_class, sections in invocation_map.items():
        if 'methods' not in sections:
            continue
        
        for method_sig, lines in sections['methods'].items():
            # 处理行号可能是单值或数组
            lines_list = lines if isinstance(lines, list) else [lines]
            
            points.append({
                'package_class': package_class,
                'signature': method_sig,
                'lines': [l for l in lines_list if l is not None]
            })
    
    return points
```

**设计决策**：
- ✅ 只处理 `methods`：当前数据只有方法调用
- ❌ 不处理 `fields`：命名规范不确定，收益低
- ❌ 不处理 `entity`：当前数据中没有
- ✅ 容错处理：无效 JSON 返回空列表

---

### 3.4 调用链构建器（builder.py）

#### 3.4.1 核心算法：DFS 递归

```python
def _dfs_expand(self, node: CallChainNode, path_visited: Set[str], current_depth: int):
    """
    深度优先展开节点
    
    Args:
        node: 当前节点
        path_visited: 路径级已访问集合（用于环检测）
        current_depth: 当前深度
    """
    # 1. 深度限制检查
    if current_depth >= self.max_depth:
        node.is_leaf = True
        logging.debug(f"Max depth {self.max_depth} reached at {node.node_id}")
        return
    
    # 2. 从统一索引查询当前方法
    method_data = self.unified_index.query_method(
        node.package_class, 
        node.method_signature
    )
    
    if not method_data:
        node.is_leaf = True
        logging.debug(f"Method not found: {node.package_class}.{node.method_signature}")
        return
    
    # 3. 更新节点信息
    node.db_method_id = method_data.get('method_id')
    
    # 4. 解析 method_invocation_map
    invocation_map_json = method_data.get('method_invocation_map', '{}')
    callable_points = InvocationPointParser.parse(invocation_map_json)
    
    if not callable_points:
        node.is_leaf = True
        return
    
    # 5. 按行号排序
    sorted_points = sorted(
        callable_points, 
        key=lambda p: min(p['lines']) if p['lines'] else 999999
    )
    
    # 6. 递归构建子树
    for point in sorted_points:
        child_key = f"{point['package_class']}|{point['signature']}"
        
        # 6.1 环检测
        if child_key in path_visited:
            child = self._create_node(point, current_depth + 1)
            child.is_cyclic = True
            child.is_leaf = True
            node.children.append(child)
            logging.debug(f"Cycle detected: {child_key}")
            continue
        
        # 6.2 创建子节点
        child = self._create_node(point, current_depth + 1)
        node.children.append(child)
        
        # 6.3 递归下探
        path_visited.add(child_key)
        self._dfs_expand(child, path_visited, current_depth + 1)
        path_visited.discard(child_key)  # 回溯
    
    # 7. 如果没有子节点，标记为叶子
    if not node.children:
        node.is_leaf = True
```

**设计决策**：
- ✅ 路径级 visited：检测真正的环（A→B→C→A）
- ❌ 不实现全局 visited：首期不需要重复检测
- ✅ 回溯机制：允许不同路径访问同一节点
- ✅ 深度限制：防止栈溢出（默认 10）

---

## 四、TDD 实施计划

### Phase 1: 基础框架（Day 1）

**目标**：搭建项目结构，实现数据模型和 Mock 工具

#### Task 1.1: 创建项目结构
- [ ] 创建 `src/jcci/call_chain/` 目录
- [ ] 创建 `tests/test_call_chain/` 目录
- [ ] 编写 `__init__.py` 文件

#### Task 1.2: 实现数据模型
- [ ] 编写 `test_models.py`（测试 CallChainNode）
- [ ] 实现 `models.py`（CallChainNode 类）
- [ ] 运行测试，确保通过

#### Task 1.3: 实现 Mock 工具
- [ ] 编写 `tests/helpers.py`（MockUnifiedIndex 等）
- [ ] 编写 `conftest.py`（pytest fixtures）

**验收标准**：
- ✅ 所有测试通过
- ✅ 可以导入所有模块

---

### Phase 2: 统一方法索引（Day 2-3）

**目标**：实现 UnifiedMethodIndex，支持基线+增量合并

#### Task 2.1: 索引加载
- [ ] 编写 `test_unified_index.py` 的加载测试
- [ ] 实现 `_load_project_methods()` 方法
- [ ] 运行测试，确保能正确加载数据

#### Task 2.2: 索引合并
- [ ] 编写合并逻辑测试（基本场景、删除过滤）
- [ ] 实现 `_build_unified_index()` 方法
- [ ] 运行测试，验证合并正确性

#### Task 2.3: 方法查询
- [ ] 编写查询测试（精确匹配、重载匹配、不存在情况）
- [ ] 实现 `query_method()` 方法
- [ ] 实现 `_extract_param_types()` 辅助方法
- [ ] 运行测试，确保匹配准确

**验收标准**：
- ✅ 单元测试覆盖率 ≥ 90%
- ✅ 能正确处理基线+增量合并
- ✅ 重载方法精确匹配

---

### Phase 3: 调用点解析器（Day 3）

**目标**：实现 InvocationPointParser，解析 method_invocation_map

#### Task 3.1: 基本解析
- [ ] 编写解析测试（标准 JSON、空值、无效 JSON）
- [ ] 实现 `parse()` 方法
- [ ] 运行测试，确保解析正确

#### Task 3.2: 边界处理
- [ ] 编写边界测试（行号为单值、数组混合）
- [ ] 完善解析逻辑
- [ ] 运行测试，确保容错

**验收标准**：
- ✅ 单元测试覆盖率 ≥ 95%
- ✅ 能处理各种 JSON 格式
- ✅ 无效输入不抛异常

---

### Phase 4: 调用链构建器（Day 4-5）

**目标**：实现 CallChainBuilder，核心 DFS 递归算法

#### Task 4.1: 基础构建
- [ ] 编写简单调用链测试（无环、3 层深度）
- [ ] 实现 `build()` 和 `_dfs_expand()` 方法
- [ ] 实现 `_create_node()` 辅助方法
- [ ] 运行测试，验证基本功能

#### Task 4.2: 环检测
- [ ] 编写环检测测试（自递归、A→B→C→A）
- [ ] 实现路径级 visited 逻辑
- [ ] 运行测试，确保环被正确检测

#### Task 4.3: 深度限制
- [ ] 编写深度限制测试
- [ ] 实现 max_depth 检查
- [ ] 运行测试，验证限制生效

#### Task 4.4: 调用点排序
- [ ] 编写排序测试（乱序行号）
- [ ] 实现按行号升序排列
- [ ] 运行测试，验证顺序正确

#### Task 4.5: 异常处理
- [ ] 编写异常测试（方法不存在、无效 JSON）
- [ ] 完善容错逻辑
- [ ] 运行测试，确保不崩溃

**验收标准**：
- ✅ 单元测试覆盖率 ≥ 90%
- ✅ 所有边界场景通过
- ✅ 环检测和深度限制正常工作

---

### Phase 5: 集成测试（Day 6）

**目标**：测试组件协作，验证完整调用链构建

#### Task 5.1: 集成测试
- [ ] 编写 `test_integration.py`
- [ ] 测试完整流程：索引 → 解析 → 构建
- [ ] 在 Mock 数据上验证

#### Task 5.2: 性能测试
- [ ] 编写性能测试（大规模索引、深层调用链）
- [ ] 优化瓶颈（如果有）
- [ ] 验证性能指标达标

**验收标准**：
- ✅ 集成测试通过
- ✅ 性能指标：索引构建 < 5s，调用链 < 1s

---

### Phase 6: 端到端测试（Day 7）

**目标**：在真实 Mall 项目上验证

#### Task 6.1: E2E 测试
- [ ] 编写 `test_e2e.py`
- [ ] 测试真实 Mall 项目的调用链
- [ ] 验证调用链完整性（无断裂）

#### Task 6.2: 与 JCCI 集成
- [ ] 在 `analyze.py` 中添加 `analyze_call_chain()` 方法
- [ ] 测试从 JCCI 主流程调用
- [ ] 验证结果正确性

**验收标准**：
- ✅ 端到端测试通过
- ✅ 在 Mall 项目上成功运行
- ✅ 调用链完整，没有断裂

---

### Phase 7: 文档与优化（Day 8）

**目标**：完善文档，代码清理

#### Task 7.1: 文档
- [ ] 编写 API 使用文档
- [ ] 编写架构说明文档
- [ ] 添加代码注释

#### Task 7.2: 代码清理
- [ ] 运行 linter（flake8/black）
- [ ] 修复警告
- [ ] 重构冗余代码

#### Task 7.3: 最终测试
- [ ] 运行所有测试
- [ ] 生成覆盖率报告
- [ ] 确保覆盖率 ≥ 90%

**验收标准**：
- ✅ 文档完整
- ✅ 代码质量达标
- ✅ 所有测试通过

---

## 五、测试案例清单

### P0 优先级（必须实现）

| ID | 测试案例 | 文件 | 状态 |
|----|---------|------|------|
| T1.1 | 基线和增量数据合并 | test_unified_index.py | ⏳ |
| T1.2 | 删除方法过滤 | test_unified_index.py | ⏳ |
| T1.3 | 重载方法精确匹配 | test_unified_index.py | ⏳ |
| T2.1 | 简单调用链构建 | test_builder.py | ⏳ |
| T2.2 | 环检测 | test_builder.py | ⏳ |
| T2.3 | 深度限制 | test_builder.py | ⏳ |
| T2.4 | 调用点排序 | test_builder.py | ⏳ |
| T2.5 | 方法不存在容错 | test_builder.py | ⏳ |

### P1 优先级（重要）

| ID | 测试案例 | 文件 | 状态 |
|----|---------|------|------|
| T3.1 | 空调用链（叶子方法） | test_builder.py | ⏳ |
| T3.2 | 自递归调用 | test_builder.py | ⏳ |
| T3.3 | 同一行多调用 | test_builder.py | ⏳ |
| T3.4 | 无效 JSON 容错 | test_parser.py | ⏳ |
| T3.5 | 复杂循环依赖 | test_builder.py | ⏳ |
| T3.6 | 大规模索引性能 | test_integration.py | ⏳ |

### P2 优先级（扩展）

| ID | 测试案例 | 文件 | 状态 |
|----|---------|------|------|
| T4.1 | 泛型参数匹配 | test_unified_index.py | ⏳ |
| T4.2 | Mall 项目真实测试 | test_e2e.py | ⏳ |
| T4.3 | 基线vs增量对比 | test_e2e.py | ⏳ |

---

## 六、风险与应对

### 6.1 技术风险

| 风险 | 影响 | 概率 | 应对措施 |
|------|------|------|---------|
| 内存占用超标 | 高 | 低 | 监控内存，必要时分页加载 |
| 递归深度过大 | 中 | 低 | 设置 max_depth=10，足够覆盖实际场景 |
| 重载匹配不准确 | 高 | 中 | 严格测试，记录告警日志 |
| 性能不达标 | 中 | 低 | 性能测试早期介入，及时优化 |

### 6.2 进度风险

| 风险 | 影响 | 概率 | 应对措施 |
|------|------|------|---------|
| 测试案例设计不充分 | 高 | 中 | Review 测试案例，补充遗漏场景 |
| TDD 节奏过慢 | 中 | 中 | 严格控制每阶段时间，必要时调整范围 |
| Mall 项目数据异常 | 中 | 低 | 提前验证数据质量，准备降级方案 |

---

## 七、成功标准

### 7.1 功能标准

- ✅ 能正确构建任意方法的调用链
- ✅ 自动合并基线和增量数据，无断裂
- ✅ 精确重载匹配，无误判
- ✅ 环检测和深度限制正常工作

### 7.2 质量标准

- ✅ 单元测试覆盖率 ≥ 90%
- ✅ 所有 P0/P1 测试案例通过
- ✅ 代码符合 PEP8 规范
- ✅ 无严重 lint 警告

### 7.3 性能标准

- ✅ Mall 项目索引构建 < 5 秒
- ✅ 单个调用链构建 < 1 秒
- ✅ 内存占用 < 50 MB

### 7.4 可用性标准

- ✅ 在真实 Mall 项目上验证通过
- ✅ API 简单易用，文档清晰
- ✅ 错误提示友好，便于调试

---

## 八、下一步行动

1. **Review 本规划文档**：确认设计方案和测试案例
2. **新开对话**：按照 TDD 流程开始 Phase 1 实现
3. **逐步推进**：每个 Phase 完成后 review，再进入下一阶段

---

**文档结束**
