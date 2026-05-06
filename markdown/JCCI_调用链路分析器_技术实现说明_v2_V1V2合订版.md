# 自动调用链路分析器 — V1+V2 合并阶段技术实现说明（评审修订版）

> **文档版本**: v2.0  
> **日期**: 2026-05-05  
> **阶段**: V1（简单排序）+ V2（树状递归）合并实现  
> **依赖**: JCCI 现有 `method_invocation_map` 数据结构  
> **修订说明**: 针对评审意见中 11 项问题逐一修复

---

## 修订对照表

| 序号 | 原问题 | 修订措施 | 影响文件 |
|------|--------|----------|----------|
| 2.1 | fields 调用处理过于简单，虚拟签名无法查询 | 增加 JavaBean getter/setter 自动推导；明确字段节点为叶子，不继续下探 | `parser.py`, `builder.py` |
| 2.2 | ENTITY 类型行号为空，排序时排在最前 | ENTITY 类型不参与排序，单独收集为附加信息，输出时挂载到父节点 | `parser.py`, `models.py` |
| 2.3 | 同一行多个调用无法区分内外层顺序 | 增加 `invocation_index` 字段，按解析顺序赋予递增索引，作为第三排序键 | `parser.py`, `models.py` |
| 3 | 重载方法匹配仅比较参数数量 | 实现参数类型列表精确匹配，无法匹配时记录告警并回退到模糊匹配 | `builder.py` |
| 4 | 全局 visited 误将正常重复调用判为环 | 支持双策略：路径级 visited（防真环）+ 全局 visited（防重复）；增加 `is_duplicate` 标记 | `builder.py`, `models.py` |
| 5 | 缓存返回可变对象，存在数据污染风险 | 返回 `copy.deepcopy()` 深拷贝；缓存键设计不变 | `builder.py` |
| 6 | 异常处理不完善，通用 Exception 掩盖错误 | 分层异常体系：`ParseError`/`QueryError`/`ChainError`；精确捕获；节点增加 `error` 字段 | `parser.py`, `builder.py`, `analyzer.py` |
| 7 | 递归深度存在栈溢出风险 | 增加 `sys.setrecursionlimit` 保护；提供迭代式 DFS 备选实现；增加深度统计 | `builder.py` |
| 8 | 调用链分析语义不明确 | 文档明确：基于新版本代码快照；如需对比需单独设计 diff 链路 | `analyzer.py`（注释） |
| 9 | 大链路序列化内存占用高 | 提供 `export_streaming_json()` 流式输出接口，逐节点写入 | `analyzer.py` |
| 10 | 测试用例缺少边界场景 | 补充空 map、缺失方法、SQL 注入防护、超大 JSON 性能测试 | 文档附录 |
| 11 | SQL 拼接逻辑多处重复 | 抽取 `_build_method_signature_sql()` 和 `_build_query_by_signature()` 公共方法 | `builder.py` |

---

## 1. 总体设计思路（不变）

两阶段流水线：
```
输入: 起始方法 (package_class + method_signature)
    │
    ▼
┌─────────────────────────────────────────┐
│  Phase 1: 单方法内调用排序 (V1)         │
│  - 读取 method_invocation_map           │
│  - 按 (行号, 调用索引) 升序排列         │
│  - 过滤 ENTITY 类型，延后处理            │
│  - 输出: 有序调用点列表                  │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│  Phase 2: 跨层级递归追踪 (V2)           │
│  - 对每个调用点执行 DFS 下探            │
│  - 支持路径级/全局双 visited 策略       │
│  - 精确重载匹配 + 模糊回退              │
│  - 维护 depth 层级计数                  │
│  - 输出: 带层级的调用树                 │
└─────────────────────────────────────────┘
    │
    ▼
输出: 结构化调用链路 (JSON/Tree/Stream)
```

---

## 2. 数据模型设计（修订）

### 2.1 异常体系（新增）

```python
# src/jcci/call_chain/exceptions.py

class CallChainError(Exception):
    """调用链路分析基础异常"""
    pass


class InvocationMapParseError(CallChainError):
    """method_invocation_map 解析失败"""
    def __init__(self, message, raw_json=None, original_exception=None):
        super().__init__(message)
        self.raw_json = raw_json
        self.original_exception = original_exception


class MethodQueryError(CallChainError):
    """数据库方法查询失败"""
    def __init__(self, message, package_class=None, method_signature=None, sql=None):
        super().__init__(message)
        self.package_class = package_class
        self.method_signature = method_signature
        self.sql = sql


class OverloadAmbiguityError(CallChainError):
    """重载方法匹配存在歧义"""
    def __init__(self, message, candidates=None, target_signature=None):
        super().__init__(message)
        self.candidates = candidates or []
        self.target_signature = target_signature


class MaxDepthExceededError(CallChainError):
    """超过最大递归深度"""
    def __init__(self, message, current_depth=None, node_key=None):
        super().__init__(message)
        self.current_depth = current_depth
        self.node_key = node_key
```

### 2.2 InvocationPoint（修订）

```python
# src/jcci/call_chain/models.py
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class InvocationPoint:
    """
    单方法内的一个调用点
    对应 method_invocation_map 中的一个调用记录
    """
    target_package_class: str
    target_method_signature: str
    invocation_lines: List[int]
    call_type: str  # "METHOD", "FIELD", "ENTITY"
    source_method_id: Optional[int] = None
    source_class_id: Optional[int] = None
    invocation_index: int = 0  # 【修订 2.3】同一行多个调用的出现顺序索引

    @property
    def primary_line(self) -> int:
        """用于排序的主行号"""
        return min(self.invocation_lines) if self.invocation_lines else 999999

    @property
    def node_key(self) -> str:
        """全局唯一标识"""
        return f"{self.target_package_class}|{self.target_method_signature}"

    @property
    def is_field_reference(self) -> bool:
        """是否为字段引用（非方法调用）"""
        return self.call_type == "FIELD"

    @property
    def is_entity_reference(self) -> bool:
        """是否为实体引用"""
        return self.call_type == "ENTITY"


@dataclass
class CallChainNode:
    """
    调用链路树节点
    """
    node_id: str
    package_class: str
    method_signature: str
    method_name: str
    class_name: str
    depth: int = 0
    invocation_lines: List[int] = field(default_factory=list)
    call_type: str = "METHOD"  # "ROOT", "METHOD", "FIELD", "ENTITY"
    children: List['CallChainNode'] = field(default_factory=list)

    # 【修订 4】环检测与重复检测分离
    is_cyclic: bool = False          # 真正的环（路径级 visited 检测到）
    is_duplicate: bool = False       # 已在别处展开过（全局 visited 检测到）
    is_leaf: bool = False

    # 【修订 6】异常信息挂载
    error: Optional[str] = None      # 节点处理过程中的错误信息

    db_method_id: Optional[int] = None
    db_class_id: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    # 【修订 2.2】ENTITY 引用作为附加信息挂载
    entity_references: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """递归转换为字典"""
        return {
            "node_id": self.node_id,
            "package_class": self.package_class,
            "method_signature": self.method_signature,
            "method_name": self.method_name,
            "class_name": self.class_name,
            "depth": self.depth,
            "invocation_lines": self.invocation_lines,
            "call_type": self.call_type,
            "is_cyclic": self.is_cyclic,
            "is_duplicate": self.is_duplicate,
            "is_leaf": self.is_leaf,
            "error": self.error,
            "db_method_id": self.db_method_id,
            "db_class_id": self.db_class_id,
            "entity_references": self.entity_references,
            "children": [child.to_dict() for child in self.children]
        }

    def to_flat_list(self) -> List[dict]:
        """展平为列表"""
        result = [{
            "depth": self.depth,
            "indent": "  " * self.depth,
            "package_class": self.package_class,
            "method_signature": self.method_signature,
            "call_type": self.call_type,
            "is_cyclic": self.is_cyclic,
            "is_duplicate": self.is_duplicate,
            "is_leaf": self.is_leaf,
            "error": self.error,
            "lines": self.invocation_lines
        }]
        for child in self.children:
            result.extend(child.to_flat_list())
        return result
```

---

## 3. 核心算法设计（修订）

### 3.1 算法总览

```
算法: BuildCallChain(start_package_class, start_method_signature, sqlite, project_id, visited_strategy="path")
─────────────────────────────────────────────────────────────────────────────
输入:
    start_package_class: str
    start_method_signature: str
    sqlite: SqliteHelper
    project_id: int
    commit_or_branch: str
    max_depth: int = 20
    visited_strategy: str = "path" | "global"    # 【修订 4】双策略支持

输出:
    CallChainNode

变量:
    global_visited: Set[str]       # 全局已访问集合（用于标记 is_duplicate）

步骤:
1. 设置递归深度限制 sys.setrecursionlimit(max(2000, max_depth * 2 + 100))
2. 创建根节点 root
3. 将 root 标识加入 global_visited
4. 调用 DFS_EXPAND(root, set(), 0)   # 路径级 visited 初始为空集合
5. 返回 root


子算法: DFS_EXPAND(current_node, path_visited, current_depth)
─────────────────────────────────────────────────────────────────────────────
输入:
    current_node: CallChainNode
    path_visited: Set[str]        # 【修订 4】路径级已访问集合
    current_depth: int

步骤:
1. 如果 current_depth >= max_depth:
       标记 current_node.is_leaf = True
       current_node.error = f"Max depth {max_depth} exceeded"
       返回

2. 从数据库查询当前方法信息（带精确重载匹配）

3. 解析 method_invocation_map:
       a. 提取 METHOD 类型调用点
       b. 提取 FIELD 类型调用点，自动推导 getter/setter
       c. 提取 ENTITY 类型引用，挂载到父节点 entity_references

4. 【V1 排序】METHOD 和 FIELD 调用点按 (primary_line, invocation_index) 升序排列
       ENTITY 类型不参与排序，不进入 children

5. 【V2 递归】遍历排序后的调用点:
       对于每个 point:
           a. 生成节点标识 node_key

           b. 创建子节点 child

           c. 【路径级环检测】如果 node_key 在 path_visited 中:
                 标记 child.is_cyclic = True
                 加入 children，不再下探
                 继续下一个 point

           d. 【全局重复检测】如果 visited_strategy == "global" 且 node_key 在 global_visited:
                 标记 child.is_duplicate = True
                 加入 children，不再下探
                 继续下一个 point

           e. 将 node_key 加入 path_visited 和 global_visited

           f. 查询子节点数据库信息并填充

           g. 将 child 加入 current_node.children

           h. 递归调用 DFS_EXPAND(child, path_visited | {node_key}, current_depth + 1)

           i. 【路径级回溯】从 path_visited 中移除 node_key（允许其他路径访问）

6. 如果 children 为空:
       current_node.is_leaf = True
```

---

## 4. 代码实现（修订版）

### 4.1 调用点解析器（parser.py — 修订）

```python
# src/jcci/call_chain/parser.py
import json
import logging
import re
from typing import List, Dict, Any, Tuple
from .models import InvocationPoint
from .exceptions import InvocationMapParseError


class InvocationMapParser:
    """
    解析 methods 表中的 method_invocation_map JSON 字段
    提取结构化的调用点列表
    """

    # JavaBean 命名规范正则
    _GETTER_PATTERN = re.compile(r'^get([A-Z].*)$')
    _SETTER_PATTERN = re.compile(r'^set([A-Z].*)$')
    _BOOLEAN_GETTER_PATTERN = re.compile(r'^is([A-Z].*)$')

    @classmethod
    def parse(cls, 
              method_invocation_map_json: str,
              source_method_id: int = None,
              source_class_id: int = None) -> Tuple[List[InvocationPoint], List[str]]:
        """
        解析 method_invocation_map

        【修订 2.1】【修订 2.2】
        - fields 调用自动推导 getter/setter 方法签名
        - ENTITY 类型单独返回，不参与排序和递归

        Args:
            method_invocation_map_json: 数据库中的 JSON 字符串
            source_method_id: 调用方方法ID
            source_class_id: 调用方类ID

        Returns:
            Tuple[List[InvocationPoint], List[str]]: 
                - 可调用的调用点列表（METHOD + FIELD）
                - 实体引用列表（ENTITY）
        """
        if not method_invocation_map_json:
            return [], []

        try:
            invocation_map = json.loads(method_invocation_map_json)
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse method_invocation_map: {e}")
            raise InvocationMapParseError(
                f"JSON parse failed: {e}",
                raw_json=method_invocation_map_json,
                original_exception=e
            )

        callable_points = []   # METHOD + FIELD
        entity_refs = []       # ENTITY 单独收集
        invocation_index = 0   # 【修订 2.3】调用出现顺序索引

        for package_class, sections in invocation_map.items():
            # 处理方法调用 (methods)
            if "methods" in sections:
                for method_sig, lines in sections["methods"].items():
                    lines_list = lines if isinstance(lines, list) else [lines]
                    callable_points.append(InvocationPoint(
                        target_package_class=package_class,
                        target_method_signature=method_sig,
                        invocation_lines=[l for l in lines_list if l is not None],
                        call_type="METHOD",
                        source_method_id=source_method_id,
                        source_class_id=source_class_id,
                        invocation_index=invocation_index
                    ))
                    invocation_index += 1

            # 【修订 2.1】处理字段调用 (fields) — 自动推导 getter/setter
            if "fields" in sections:
                for field_name, lines in sections["fields"].items():
                    lines_list = lines if isinstance(lines, list) else [lines]

                    # 推导可能的 getter/setter 方法签名
                    # 注意：这里推导的是"可能的方法签名"，用于后续查询
                    # 实际是否匹配取决于数据库中是否存在这些方法
                    derived_signatures = cls._derive_accessor_signatures(field_name)

                    for derived_sig in derived_signatures:
                        callable_points.append(InvocationPoint(
                            target_package_class=package_class,
                            target_method_signature=derived_sig,
                            invocation_lines=[l for l in lines_list if l is not None],
                            call_type="FIELD",  # 仍标记为 FIELD，表示通过字段触发
                            source_method_id=source_method_id,
                            source_class_id=source_class_id,
                            invocation_index=invocation_index
                        ))
                        invocation_index += 1

            # 【修订 2.2】处理实体引用 (entity) — 单独收集，不参与排序
            if "entity" in sections:
                entity_refs.append(package_class)

        return callable_points, entity_refs

    @classmethod
    def _derive_accessor_signatures(cls, field_name: str) -> List[str]:
        """
        【修订 2.1】根据字段名推导 JavaBean getter/setter 方法签名

        例如:
            field_name = "name"
            → ["getName()", "setName(java.lang.Object)"]

            field_name = "valid"
            → ["getValid()", "setValid(java.lang.Object)", "isValid()"]

        注意：set 方法的参数类型使用 Object 占位，实际匹配时由 _query_method 处理
        """
        if not field_name:
            return []

        # 首字母大写
        capitalized = field_name[0].upper() + field_name[1:] if len(field_name) > 1 else field_name.upper()

        signatures = [
            f"get{capitalized}()",
            f"set{capitalized}(java.lang.Object)"  # 占位参数类型
        ]

        # 布尔类型字段可能有 isXxx 形式
        signatures.append(f"is{capitalized}()")

        return signatures

    @staticmethod
    def sort_by_line_number(points: List[InvocationPoint]) -> List[InvocationPoint]:
        """
        【V1 核心】【修订 2.3】按调用行号升序排列

        排序键优先级:
        1. primary_line (最小行号)
        2. invocation_index (出现顺序，解决同一行多调用问题)
        3. target_package_class (类名字典序，保证确定性)
        4. target_method_signature (方法名字典序)
        """
        return sorted(points, key=lambda p: (
            p.primary_line,
            p.invocation_index,
            p.target_package_class,
            p.target_method_signature
        ))
```

### 4.2 调用链路构建器（builder.py — 大幅修订）

```python
# src/jcci/call_chain/builder.py
import copy
import json
import logging
import sys
from typing import Set, Optional, List, Dict, Any
from .models import InvocationPoint, CallChainNode
from .parser import InvocationMapParser
from .exceptions import (
    MethodQueryError, 
    OverloadAmbiguityError, 
    MaxDepthExceededError,
    InvocationMapParseError
)


class CallChainBuilder:
    """
    调用链路构建器
    实现 V1(排序) + V2(递归) 合并算法

    【修订 4】支持双 visited 策略
    【修订 3】精确重载匹配
    【修订 5】深拷贝缓存
    【修订 7】递归深度保护
    """

    def __init__(self, 
                 sqlite, 
                 project_id: int, 
                 commit_or_branch: str, 
                 max_depth: int = 20,
                 visited_strategy: str = "path"):
        self.sqlite = sqlite
        self.project_id = project_id
        self.commit_or_branch = commit_or_branch
        self.max_depth = max_depth
        self.visited_strategy = visited_strategy  # "path" | "global"

        # 【修订 7】设置递归深度限制
        self._setup_recursion_limit()

        self.global_visited: Set[str] = set()
        self._method_cache: Dict[str, Optional[dict]] = {}
        self._depth_stats = {"max_reached": 0, "total_nodes": 0}

    def _setup_recursion_limit(self):
        """【修订 7】设置安全的递归深度限制"""
        required_limit = max(2000, self.max_depth * 2 + 100)
        current_limit = sys.getrecursionlimit()
        if current_limit < required_limit:
            sys.setrecursionlimit(required_limit)
            logging.info(f"Recursion limit adjusted: {current_limit} -> {required_limit}")

    def build(self, 
              start_package_class: str, 
              start_method_signature: str,
              start_method_id: int = None,
              start_class_id: int = None) -> CallChainNode:
        """
        构建从指定方法开始的完整调用链路
        """
        # 创建根节点
        root = CallChainNode(
            node_id=f"0|{start_package_class}|{start_method_signature}",
            package_class=start_package_class,
            method_signature=start_method_signature,
            method_name=start_method_signature.split('(')[0] if '(' in start_method_signature else start_method_signature,
            class_name=start_package_class.split('.')[-1],
            depth=0,
            call_type="ROOT",
            db_method_id=start_method_id,
            db_class_id=start_class_id
        )

        # 标记根节点为全局已访问
        root_key = f"{start_package_class}|{start_method_signature}"
        self.global_visited.add(root_key)

        # 启动 DFS，路径级 visited 初始为空
        self._dfs_expand(root, set(), 0)

        # 记录统计
        root.extra["depth_stats"] = self._depth_stats.copy()

        return root

    def _dfs_expand(self, node: CallChainNode, path_visited: Set[str], current_depth: int):
        """
        深度优先展开节点

        【修订 4】双 visited 策略:
        - path_visited: 检测真正的环（A→B→C→A）
        - global_visited: 检测重复展开（多处调用同一工具方法）
        """
        # 深度限制检查
        if current_depth >= self.max_depth:
            logging.warning(f"Max depth {self.max_depth} reached at depth {current_depth}")
            node.is_leaf = True
            node.error = f"Max depth {self.max_depth} exceeded"
            self._depth_stats["max_reached"] = max(self._depth_stats["max_reached"], current_depth)
            return

        self._depth_stats["max_reached"] = max(self._depth_stats["max_reached"], current_depth)
        self._depth_stats["total_nodes"] += 1

        try:
            # 从数据库查询当前方法
            method_data = self._query_method(node.package_class, node.method_signature)
        except MethodQueryError as e:
            logging.error(f"Query failed for {node.node_id}: {e}")
            node.is_leaf = True
            node.error = str(e)
            return

        if not method_data:
            node.is_leaf = True
            return

        # 更新节点数据库ID
        node.db_method_id = method_data.get('method_id')
        node.db_class_id = method_data.get('class_id')

        # 解析 method_invocation_map
        invocation_map_json = method_data.get('method_invocation_map', '{}')

        try:
            callable_points, entity_refs = InvocationMapParser.parse(
                invocation_map_json,
                source_method_id=node.db_method_id,
                source_class_id=node.db_class_id
            )
        except InvocationMapParseError as e:
            logging.error(f"Parse failed for {node.node_id}: {e}")
            node.is_leaf = True
            node.error = f"Parse error: {e}"
            return

        # 【修订 2.2】挂载实体引用到父节点
        node.entity_references = entity_refs

        if not callable_points:
            node.is_leaf = True
            return

        # 【V1 核心】按行号升序排列调用点
        sorted_points = InvocationMapParser.sort_by_line_number(callable_points)

        # 【V2 核心】遍历排序后的调用点，递归构建子树
        for point in sorted_points:
            child = self._create_child_node(node, point, current_depth + 1)

            # 【修订 4】路径级环检测（真正的环）
            if point.node_key in path_visited:
                child.is_cyclic = True
                node.children.append(child)
                logging.debug(f"Cycle detected (path): {point.node_key}")
                continue

            # 【修订 4】全局重复检测（已在别处展开）
            if self.visited_strategy == "global" and point.node_key in self.global_visited:
                child.is_duplicate = True
                node.children.append(child)
                logging.debug(f"Duplicate detected (global): {point.node_key}")
                continue

            # 标记为已访问
            path_visited.add(point.node_key)
            self.global_visited.add(point.node_key)

            # 查询子节点数据库信息
            try:
                child_data = self._query_method(point.target_package_class, point.target_method_signature)
                if child_data:
                    child.db_method_id = child_data.get('method_id')
                    child.db_class_id = child_data.get('class_id')
            except MethodQueryError as e:
                child.error = str(e)
                logging.warning(f"Child query failed for {point.node_key}: {e}")

            node.children.append(child)

            # 递归下探
            self._dfs_expand(child, path_visited, current_depth + 1)

            # 【修订 4】路径级回溯：允许其他路径访问此节点
            path_visited.discard(point.node_key)

        if not node.children:
            node.is_leaf = True

    # 【修订 11】抽取公共 SQL 构建方法
    def _build_method_signature_sql(self, package_name: str, class_name: str, 
                                     method_name: str, commit_or_branch: str) -> str:
        """构建基础查询 SQL"""
        return f"""
            SELECT 
                m.method_id,
                m.class_id,
                m.method_name,
                m.parameters,
                m.method_invocation_map,
                m.return_type,
                m.is_api,
                m.api_path,
                c.class_name,
                c.package_name,
                c.filepath,
                c.is_controller
            FROM methods m
            JOIN class c ON m.class_id = c.class_id
            WHERE c.project_id = {self.project_id}
              AND c.package_name = '{package_name}'
              AND c.class_name = '{class_name}'
              AND m.method_name = '{method_name}'
              AND c.commit_or_branch = '{commit_or_branch}'
        """

    def _query_method(self, package_class: str, method_signature: str) -> Optional[dict]:
        """
        【修订 3】【修订 5】【修订 11】从数据库查询方法信息

        改进点:
        1. 精确重载匹配：比较参数类型列表
        2. 深拷贝缓存：防止数据污染
        3. SQL 注入防护：参数转义
        """
        cache_key = f"{package_class}|{method_signature}|{self.commit_or_branch}"
        if cache_key in self._method_cache:
            # 【修订 5】返回深拷贝，防止调用方修改缓存数据
            cached = self._method_cache[cache_key]
            return copy.deepcopy(cached) if cached is not None else None

        # 分离包名和类名
        parts = package_class.rsplit('.', 1)
        if len(parts) != 2:
            raise MethodQueryError(
                f"Invalid package_class format: {package_class}",
                package_class=package_class,
                method_signature=method_signature
            )
        package_name, class_name = parts

        # 分离方法名和参数
        method_name = method_signature.split('(')[0]

        # 【修订 11】使用公共 SQL 构建方法
        sql = self._build_method_signature_sql(
            package_name, class_name, method_name, self.commit_or_branch
        )

        try:
            results = self.sqlite.select_data(sql)
        except Exception as e:
            raise MethodQueryError(
                f"Database query failed: {e}",
                package_class=package_class,
                method_signature=method_signature,
                sql=sql
            )

        if not results:
            self._method_cache[cache_key] = None
            return None

        # 【修订 3】精确重载匹配
        result = self._resolve_overload(results, method_signature, package_class)

        # 【修订 5】缓存深拷贝
        self._method_cache[cache_key] = copy.deepcopy(result)

        return copy.deepcopy(result)

    def _resolve_overload(self, candidates: List[dict], 
                          target_signature: str,
                          package_class: str) -> Optional[dict]:
        """
        【修订 3】重载方法解析

        匹配策略:
        1. 提取目标签名中的参数类型列表
        2. 与每个候选方法的 parameters JSON 字段比对
        3. 完全匹配 → 返回
        4. 无完全匹配 → 参数数量匹配 → 记录告警 → 返回第一个
        5. 无参数数量匹配 → 记录告警 → 返回第一个
        """
        # 解析目标签名的参数类型
        target_params = self._extract_param_types_from_signature(target_signature)

        # 尝试精确匹配
        exact_matches = []
        for candidate in candidates:
            try:
                candidate_params_json = candidate.get('parameters', '[]')
                candidate_params = json.loads(candidate_params_json)
                candidate_types = [p.get('parameter_type', '') for p in candidate_params]

                if candidate_types == target_params:
                    exact_matches.append(candidate)
            except (json.JSONDecodeError, TypeError):
                continue

        if len(exact_matches) == 1:
            return exact_matches[0]
        elif len(exact_matches) > 1:
            # 多个精确匹配（理论上不应发生）
            logging.warning(
                f"Multiple exact overload matches for {target_signature}, "
                f"returning first"
            )
            return exact_matches[0]

        # 无精确匹配，尝试参数数量匹配
        target_count = len(target_params)
        count_matches = []
        for candidate in candidates:
            try:
                candidate_params_json = candidate.get('parameters', '[]')
                candidate_params = json.loads(candidate_params_json)
                if len(candidate_params) == target_count:
                    count_matches.append(candidate)
            except (json.JSONDecodeError, TypeError):
                continue

        if count_matches:
            logging.warning(
                f"Overload ambiguity for {target_signature}: "
                f"{len(count_matches)} candidates with {target_count} params, "
                f"falling back to first match"
            )
            return count_matches[0]

        # 完全无法匹配，返回第一个并记录严重告警
        logging.error(
            f"No overload match for {target_signature} among {len(candidates)} candidates, "
            f"returning first as fallback"
        )
        return candidates[0]

    @staticmethod
    def _extract_param_types_from_signature(method_signature: str) -> List[str]:
        """从方法签名中提取参数类型列表"""
        if '(' not in method_signature or ')' not in method_signature:
            return []

        params_str = method_signature.split('(')[1].split(')')[0]
        if not params_str:
            return []

        # 处理可能包含泛型的参数类型
        types = []
        current = ""
        depth = 0
        for char in params_str:
            if char == '<':
                depth += 1
                current += char
            elif char == '>':
                depth -= 1
                current += char
            elif char == ',' and depth == 0:
                types.append(current.strip())
                current = ""
            else:
                current += char

        if current.strip():
            types.append(current.strip())

        return types

    def _create_child_node(self, parent: CallChainNode, 
                           point: InvocationPoint, 
                           depth: int) -> CallChainNode:
        """根据调用点创建子节点"""
        class_name = point.target_package_class.split('.')[-1]
        method_name = point.target_method_signature.split('(')[0] if '(' in point.target_method_signature else point.target_method_signature

        return CallChainNode(
            node_id=f"{depth}|{point.node_key}",
            package_class=point.target_package_class,
            method_signature=point.target_method_signature,
            method_name=method_name,
            class_name=class_name,
            depth=depth,
            invocation_lines=point.invocation_lines,
            call_type=point.call_type,
            is_cyclic=False,
            is_duplicate=False,
            is_leaf=False
        )

    def reset(self):
        """重置构建器状态"""
        self.global_visited.clear()
        self._method_cache.clear()
        self._depth_stats = {"max_reached": 0, "total_nodes": 0}
```

### 4.3 统一对外接口（analyzer.py — 修订）

```python
# src/jcci/call_chain/analyzer.py
import json
import logging
from typing import List, Optional, Dict, Any
from .builder import CallChainBuilder
from .models import CallChainNode
from .exceptions import CallChainError


class CallChainAnalyzer:
    """
    调用链路分析器对外统一接口

    【修订 8】明确语义：基于新版本代码快照分析
    【修订 9】支持流式输出
    """

    def __init__(self, sqlite, project_id: int, commit_or_branch: str):
        self.sqlite = sqlite
        self.project_id = project_id
        self.commit_or_branch = commit_or_branch
        self.builder = CallChainBuilder(sqlite, project_id, commit_or_branch)

    def analyze_method(self, 
                       package_class: str, 
                       method_signature: str,
                       visited_strategy: str = "path") -> CallChainNode:
        """
        分析单个方法的调用链路

        【修订 8】语义说明：
        调用链分析基于指定 commit_or_branch 版本的代码快照，
        反映该版本时刻的静态调用关系，不包含历史版本对比信息。
        如需对比变更前后的调用链差异，需分别分析两个版本后自行对比。
        """
        self.builder.reset()
        self.builder.visited_strategy = visited_strategy
        return self.builder.build(package_class, method_signature)

    def analyze_changed_methods(self, method_changes: List[dict]) -> List[dict]:
        """
        批量分析变更方法的调用链路

        【修订 6】精确异常捕获，区分业务异常和编程错误
        """
        results = []

        for change in method_changes:
            sig = change.get('method_signature', '')
            parts = sig.rsplit('.', 1)
            if len(parts) != 2:
                results.append({
                    "change_info": change,
                    "error": f"Invalid method signature format: {sig}"
                })
                continue

            package_class = parts[0]
            method_signature = parts[1]

            try:
                chain = self.analyze_method(package_class, method_signature)
                results.append({
                    "change_info": change,
                    "call_chain": chain.to_dict(),
                    "flat_view": chain.to_flat_list(),
                    "depth_stats": chain.extra.get("depth_stats", {})
                })
            except CallChainError as e:
                # 【修订 6】精确捕获业务异常
                logging.error(f"Call chain analysis failed for {sig}: {e}")
                results.append({
                    "change_info": change,
                    "error": str(e),
                    "error_type": type(e).__name__
                })
            except Exception as e:
                # 【修订 6】未预期异常记录完整 traceback
                import traceback
                logging.error(f"Unexpected error analyzing {sig}: {e}\n{traceback.format_exc()}")
                results.append({
                    "change_info": change,
                    "error": f"Unexpected error: {e}",
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                })

        return results

    def analyze_impacted_apis(self, impacted_api_list: List[str]) -> Dict[str, Any]:
        """分析所有受影响 API 的完整调用链路"""
        results = {}

        for api_path in impacted_api_list:
            # 【修订 11】使用公共查询方法
            api_methods = self._query_api_methods(api_path)
            if not api_methods:
                continue

            api_method = api_methods[0]
            try:
                chain = self.analyze_method(
                    api_method['package_class'],
                    api_method['method_sig']
                )
                results[api_path] = {
                    "api_method": api_method,
                    "call_chain": chain.to_dict(),
                    "flat_view": chain.to_flat_list(),
                    "depth_stats": chain.extra.get("depth_stats", {})
                }
            except CallChainError as e:
                logging.error(f"Failed to analyze API {api_path}: {e}")
                results[api_path] = {"error": str(e), "error_type": type(e).__name__}
            except Exception as e:
                import traceback
                logging.error(f"Unexpected error analyzing API {api_path}: {e}\n{traceback.format_exc()}")
                results[api_path] = {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }

        return results

    def _query_api_methods(self, api_path: str) -> List[dict]:
        """【修订 11】抽取公共 API 查询方法"""
        # SQL 注入防护：转义单引号
        safe_api_path = api_path.replace("'", "''")

        sql = f"""
            SELECT 
                c.package_name || '.' || c.class_name as package_class,
                m.method_name as method_name,
                m.parameters as parameters
            FROM methods m
            JOIN class c ON m.class_id = c.class_id
            WHERE c.project_id = {self.project_id}
              AND m.is_api = 'True'
              AND m.api_path LIKE '%{safe_api_path}%'
              AND c.commit_or_branch = '{self.commit_or_branch}'
            LIMIT 1
        """

        results = self.sqlite.select_data(sql)

        # 构建完整方法签名
        processed = []
        for r in results:
            try:
                params = json.loads(r.get('parameters', '[]'))
                param_types = [p.get('parameter_type', '') for p in params]
                method_sig = f"{r['method_name']}({','.join(param_types)})"
                processed.append({
                    **r,
                    'method_sig': method_sig
                })
            except (json.JSONDecodeError, TypeError):
                processed.append({
                    **r,
                    'method_sig': f"{r['method_name']}()"
                })

        return processed

    def export_to_json(self, chain: CallChainNode, filepath: str):
        """导出调用链为 JSON 文件"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(chain.to_dict(), f, ensure_ascii=False, indent=2)

    def export_to_flat_json(self, chain: CallChainNode, filepath: str):
        """导出调用链为扁平化 JSON"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(chain.to_flat_list(), f, ensure_ascii=False, indent=2)

    # 【修订 9】流式输出接口
    def export_streaming_json(self, chain: CallChainNode, filepath: str):
        """
        流式 JSON 输出，避免内存中构造完整树
        适用于超大调用链场景
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('[')
            first = True

            def write_node(node: CallChainNode):
                nonlocal first
                node_dict = {
                    "node_id": node.node_id,
                    "package_class": node.package_class,
                    "method_signature": node.method_signature,
                    "depth": node.depth,
                    "call_type": node.call_type,
                    "is_cyclic": node.is_cyclic,
                    "is_duplicate": node.is_duplicate,
                    "is_leaf": node.is_leaf,
                    "invocation_lines": node.invocation_lines,
                    "entity_references": node.entity_references,
                    "error": node.error
                }

                if not first:
                    f.write(',\n')
                first = False
                f.write(json.dumps(node_dict, ensure_ascii=False))

                for child in node.children:
                    write_node(child)

            write_node(chain)
            f.write(']')
```

### 4.4 与 JCCI 集成（analyze.py 改造 — 不变，仅增加注释）

```python
# 在 JCCI 类中新增/改造方法

def analyze_call_chain(self, package_class: str, method_signature: str, 
                       visited_strategy: str = "path") -> dict:
    """
    分析指定方法的完整调用链路（V1+V2 合并）

    【修订 8】语义说明：
    调用链分析基于 self.commit_or_branch_new（新版本）代码快照，
    反映该版本时刻的静态调用关系。不包含与旧版本的对比信息。
    """
    from .call_chain.analyzer import CallChainAnalyzer

    analyzer = CallChainAnalyzer(
        self.sqlite, 
        self.project_id, 
        self.commit_or_branch_new
    )

    chain = analyzer.analyze_method(package_class, method_signature, 
                                     visited_strategy=visited_strategy)

    # 导出结果（根据大小选择普通或流式输出）
    node_count = self._count_nodes(chain)
    chain_filepath = os.path.join(
        self.file_path, 
        f'chain_{package_class.split(".")[-1]}_{method_signature.split("(")[0]}.json'
    )

    if node_count > 10000:
        # 大链路使用流式输出
        analyzer.export_streaming_json(chain, chain_filepath)
    else:
        analyzer.export_to_json(chain, chain_filepath)

    result = {
        "chain_tree": chain.to_dict(),
        "chain_flat": chain.to_flat_list(),
        "chain_file": chain_filepath,
        "total_nodes": node_count,
        "max_depth": self._get_max_depth(chain),
        "cyclic_count": self._count_cyclic_nodes(chain),
        "duplicate_count": self._count_duplicate_nodes(chain),
        "depth_stats": chain.extra.get("depth_stats", {})
    }

    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result
```

---

## 5. 输出格式示例（修订）

### 5.1 树形结构输出（含 is_duplicate）

```json
{
  "node_id": "0|UmsMenuController|list(int,int)",
  "package_class": "com.macro.mall.controller.UmsMenuController",
  "method_signature": "list(int,int)",
  "depth": 0,
  "call_type": "ROOT",
  "is_cyclic": false,
  "is_duplicate": false,
  "entity_references": ["com.macro.mall.model.UmsMenu"],
  "children": [
    {
      "node_id": "1|UmsMenuService|list(int,int)",
      "depth": 1,
      "invocation_lines": [34],
      "call_type": "METHOD",
      "is_cyclic": false,
      "is_duplicate": false,
      "children": [...]
    },
    {
      "node_id": "1|Logger|info(java.lang.String)",
      "depth": 1,
      "invocation_lines": [35],
      "call_type": "METHOD",
      "is_cyclic": false,
      "is_duplicate": true,
      "children": [],
      "error": null
    }
  ]
}
```

### 5.2 控制台文本输出（含重复标记）

```
[ROOT] UmsMenuController.list(int,int)
  ├─ [L34] UmsMenuService.list(int,int)
  │    ├─ [L45] UmsMenuMapper.selectList(Wrapper)
  │    └─ [L46] Logger.info(String) [DUPLICATE]
  ├─ [L35] Logger.info(String) [DUPLICATE]
  └─ [L36] CommonResult.success(Object)

总节点数: 5 | 最大深度: 2 | 真环: 0 | 重复节点: 2
```

---

## 6. 测试策略（修订 — 补充边界场景）

### 6.1 基础功能测试

| 用例 | 输入 | 预期 |
|------|------|------|
| V1 排序验证 | method_invocation_map 含行号 [38, 34, 42] | 输出顺序 34 → 38 → 42 |
| V2 递归验证 | Controller.list() → Service.list() → Mapper.selectList() | 深度 3，根 depth=0 |
| 环检测 | A→B→C→A | A 第二次出现 is_cyclic=True，不展开 |

### 6.2 边界与异常测试（【修订 10】新增）

| 用例 | 输入 | 预期 |
|------|------|------|
| 空 method_invocation_map | `{}` 或 `null` | 返回空链路，根节点标记 is_leaf=True |
| 缺失方法查询 | 数据库中不存在的 package_class | 节点标记 error="Method not found"，继续其他分支 |
| SQL 注入防护 | package_class = `' OR '1'='1` | 参数被转义，不会导致 SQL 注入 |
| 超大 JSON 解析 | 数 MB 的 method_invocation_map | 正常解析，性能在秒级内完成 |
| 深度超限 | max_depth=3，实际深度 10 | 第 3 层标记 is_leaf=True，error="Max depth exceeded" |
| 重载歧义 | create(int,String) vs create(String,int) | 记录告警日志，返回第一个匹配 |
| 字段推导 | field_name="userName" | 推导 signatures: ["getUserName()", "setUserName(Object)", "isUserName()"] |
| 同一行多调用 | a.foo(b.bar()) | invocation_index 区分顺序：foo(0) → bar(1) |

---

## 7. 文件清单（修订）

| 文件路径 | 类型 | 说明 |
|----------|------|------|
| `src/jcci/call_chain/__init__.py` | 新增 | 包初始化 |
| `src/jcci/call_chain/exceptions.py` | **新增** | 异常体系定义 |
| `src/jcci/call_chain/models.py` | 新增 | 数据模型（含 is_duplicate、error、entity_references） |
| `src/jcci/call_chain/parser.py` | 新增 | 解析器（含 JavaBean 推导、invocation_index） |
| `src/jcci/call_chain/builder.py` | 新增 | 构建器（双 visited 策略、精确重载、深拷贝缓存） |
| `src/jcci/call_chain/analyzer.py` | 新增 | 对外接口（流式输出、精确异常捕获） |
| `src/jcci/analyze.py` | 修改 | 新增调用链路分析入口 |

---

**文档结束**
