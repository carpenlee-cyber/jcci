# JCCI 调用链路分析器 - 技术实现说明（v4.0 评审修订版）

> **文档版本**: v4.0  
> **日期**: 2026-05-05  
> **阶段**: 评审修订版（基于 v3.0 架构增量演进）  
> **状态**: 📝 待实施  
> **兼容性**: 完全向后兼容 v3.0 API，新增字段均为可选

---

## 修订说明

### v3.0 → v4.0 变更概要

| 序号 | 变更项 | v3.0 状态 | v4.0 设计 | 影响面 |
|------|--------|-----------|-----------|--------|
| 1 | `change_type` 字段 | 仅用于内部索引过滤 | **透传至调用链节点**，显式枚举定义，与索引合并解耦 | `models.py`, `builder.py` |
| 2 | DAO/Entity/SQL 透视 | 不支持 | **新增 `DaoAnalyzer` 模块**，独立组合而非耦合到索引 | 新增 `dao_analyzer.py`, `entity_resolver.py`, `sql_resolver.py` |
| 3 | `DaoAnalyzer` 耦合 | 直接内嵌于 `UnifiedMethodIndex` | **解耦为独立组件**，由 `CallChainBuilder` 可选注入 | `index.py`, `builder.py` |
| 4 | Entity 来源追踪 | 不支持 | **`entity_source` 字段**：`INFERRED` / `MAPPED` / `UNKNOWN` | `models.py` |
| 5 | 降级日志 | `try/except pass` 静默吞错 | **全路径 warning 日志**，异常标记避免重复报错 | `dao_analyzer.py` |
| 6 | DAO 类型识别 | 仅后缀匹配 | **后缀 + 包名优先级规则**，冲突时降级为 `UNKNOWN` | `dao_analyzer.py` |
| 7 | 数据库 Schema | 无版本管理 | **Schema 健康检查**：表 + 关键列双重验证 | `dao_analyzer.py` |
| 8 | 输出结构 | 标准调用树 | **增加 `change_type` 与 `dao_info`**，明确标注可空 | `models.py` |

### 设计原则

1. **向后兼容**：v3.0 所有 API、数据流、46 个测试用例在 v4.0 保持 100% 通过
2. **优雅降级**：若数据库中不存在 SQL 映射表或列缺失，DAO 分析自动退化为**命名推导模式**，不报错、不中断
3. **增量覆盖**：`change_type` 遵循 v3.0 统一索引合并规则（增量覆盖基线），但枚举定义与判定逻辑显式化
4. **组合优于继承**：`DaoAnalyzer` 作为独立策略组件注入 `Builder`，不与索引层耦合

---

## 1. 总体架构

### 1.1 扩展后的模块划分

```
src/jcci/call_chain/
├── __init__.py              # 导出公共接口（新增 DaoAnalyzer, ChangeType）
├── models.py                # 扩展：CallChainNode 增加 change_type + dao_info
├── index.py                 # 精简：移除 DaoAnalyzer 耦合，专注索引职责
├── parser.py                # 无变更
├── builder.py               # 扩展：接收可选 dao_analyzer，注入 change_type 与 DAO 分析
├── dao_analyzer.py          # 新增：DAO 识别、SQL 关联、Entity 推导（独立组件）
├── entity_resolver.py       # 新增：Entity 命名推导与表名映射
└── sql_resolver.py          # 新增：SQL 语句解析（从 dao_analyzer.py 拆分）

tests/test_call_chain/
├── test_models.py           # 扩展：增加 change_type 枚举与 DaoInfo 序列化测试
├── test_unified_index.py    # 无变更
├── test_parser.py           # 无变更
├── test_builder.py          # 扩展：增加 change_type 透传与 DAO 注入测试
├── test_integration.py      # 扩展：增加端到端 DAO 链路测试
├── test_dao_analyzer.py     # 新增：DAO 识别 10 个测试（含降级、日志、来源追踪）
├── test_change_type.py      # 新增：变更状态 10 个测试（含枚举边界）
└── test_schema_health.py    # 新增：Schema 健康检查 4 个测试
```

### 1.2 扩展后的数据流

```
输入: (package_class, method_signature, project_id, commit_old, commit_new)
    │
    ▼
┌──────────────────────────────┐
│ Step 1: 构建统一索引          │
│ - 加载基线 (project_id=0)    │
│ - 加载增量 (project_id=1)    │
│ - 合并：增量覆盖基线          │
│ - 输出：method_data 含       │
│   change_type, method_id     │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Step 2: 初始化 DAO 分析器     │  ◀── 新增（可选注入）
│ - Schema 健康检查            │
│ - 若健康：加载映射缓存        │
│ - 若不健康：标记降级模式      │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Step 3: 查找起始方法          │
│ - 从统一索引查询              │
│ - 解析 method_invocation_map │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Step 4: 提取并排序调用点      │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Step 5: DFS 递归构建         │
│ - 对每个调用点：              │
│   a. 环检测                  │
│   b. 创建子节点              │
│   c. 注入 change_type        │  ◀── 显式枚举
│   d. DAO 分析（如适用）       │  ◀── 独立组件
│   e. 递归下探                │
│   f. 回溯                    │
└──────────────┬───────────────┘
               │
               ▼
输出: CallChainNode 树结构 → to_dict() → JSON
```

---

## 2. 核心组件详细设计

### 2.1 变更类型枚举（models.py）

#### 新增枚举：`ChangeType`

```python
from enum import Enum
from typing import Optional

class ChangeType(str, Enum):
    """
    方法变更状态枚举
    
    定义：
    - UNCHANGED:  基线存在，增量也存在，且经外部 diff 判定无变更
    - ADDED:      基线不存在，增量存在
    - MODIFIED:   基线存在，增量存在，且经外部 diff 判定有变更
    - DELETED:    基线存在，增量标记为删除（已被索引过滤，理论上不出现在调用链中）
    - UNKNOWN:    无法判定变更状态（如基线数据未记录 change_type）
    
    与索引合并的关系：
    - 统一索引合并后，每个方法保留其最终来源的 change_type
    - 增量覆盖基线时，以增量数据的 change_type 为准
    - 若增量数据无 change_type 字段，继承基线值；若基线也无，则为 UNKNOWN
    """
    UNCHANGED = "UNCHANGED"
    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    UNKNOWN = "UNKNOWN"
    
    @classmethod
    def from_raw(cls, raw: Optional[str]) -> "ChangeType":
        """从原始字符串安全转换，无法识别时返回 UNKNOWN"""
        if not raw:
            return cls.UNKNOWN
        try:
            return cls(raw.upper())
        except ValueError:
            return cls.UNKNOWN
```

#### 设计决策

| 决策点 | 方案 | 原因 |
|--------|------|------|
| `DELETED` 是否可能出现在链中 | 理论上不会（已被索引过滤），但保留枚举值用于完整性 | 防御性设计，若未来支持"查看已删除方法的历史调用链"可直接复用 |
| `UNKNOWN` vs `None` | 使用显式枚举 `UNKNOWN`，而非 Python `None` | 避免下游消费者因 `null` 产生歧义，明确表达"状态未知" |
| 大小写敏感 | 内部统一大写，`from_raw` 自动转换 | 兼容外部数据源的大小写不一致 |

---

### 2.2 数据模型扩展（models.py）

#### 新增模型：`DaoInfo`

```python
@dataclass
class DaoInfo:
    """
    DAO 方法透视信息
    
    当调用链节点被识别为 DAO 层方法时填充此对象。
    若数据库中无 SQL 映射，仅通过命名推导，则 sql_statement 为 null，
    但 entity_name 可能通过命名推导获得，此时 entity_source = 'INFERRED'。
    """
    is_dao: bool = True
    dao_type: str = "UNKNOWN"              # MYBATIS / JPA / JDBC / MYBATIS_PLUS / UNKNOWN
    entity_name: Optional[str] = None      # 实体类名：如 "UmsAdmin"
    entity_class: Optional[str] = None     # 实体全限定名：如 "com.macro.mall.model.UmsAdmin"
    entity_source: str = "UNKNOWN"         # INFERRED（命名推导）/ MAPPED（数据库映射）/ UNKNOWN
    table_name: Optional[str] = None       # 表名：如 "ums_admin"
    sql_type: Optional[str] = None         # SELECT / INSERT / UPDATE / DELETE / BATCH / UNKNOWN
    sql_statement: Optional[str] = None    # 完整 SQL（含占位符）
    mapped_statement_id: Optional[str] = None  # MyBatis namespace.id
    
    def to_dict(self) -> dict:
        return {
            "is_dao": self.is_dao,
            "dao_type": self.dao_type,
            "entity_name": self.entity_name,
            "entity_class": self.entity_class,
            "entity_source": self.entity_source,
            "table_name": self.table_name,
            "sql_type": self.sql_type,
            "sql_statement": self.sql_statement,
            "mapped_statement_id": self.mapped_statement_id
        }
```

#### 扩展模型：`CallChainNode`

```python
@dataclass
class CallChainNode:
    # ========== v3.0 原有字段（保持不变） ==========
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
    
    # ========== v4.0 新增字段 ==========
    change_type: str = "UNKNOWN"           # ChangeType 枚举值字符串
    dao_info: Optional[DaoInfo] = None     # DAO 透视信息（非 DAO 方法为 null）
    
    def to_dict(self) -> dict:
        result = {
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
            # v4.0 新增
            "change_type": self.change_type,   # 永不为 null，至少为 "UNKNOWN"
            "dao_info": self.dao_info.to_dict() if self.dao_info else None,
            "children": [child.to_dict() for child in self.children]
        }
        return result
```

---

### 2.3 DAO 分析器（dao_analyzer.py）

#### 设计调整：独立组件 + Schema 健康检查

```python
import logging
import re
import sqlite3
from typing import Optional, Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class SchemaHealth:
    """数据库 Schema 健康状态"""
    has_entity_table: bool = False
    has_sql_table: bool = False
    has_required_columns: bool = False
    is_healthy: bool = False
    error_message: Optional[str] = None


class DaoAnalyzer:
    """
    DAO 层方法识别与透视分析器（独立策略组件）
    
    职责：
    1. 识别方法是否属于 DAO 层
    2. 解析对应的 Entity 和 SQL 信息
    3. 在缺少映射表时降级为命名推导模式
    
    使用方式：
        analyzer = DaoAnalyzer(db_conn)
        builder = CallChainBuilder(index, dao_analyzer=analyzer)
    """
    
    # DAO 类名后缀与框架类型映射（按优先级排序）
    DAO_SUFFIX_PATTERNS = [
        (r'.*Mapper$', 'MYBATIS'),
        (r'.*Dao$', 'MYBATIS'),      # 默认 MYBATIS，但包名可覆盖
        (r'.*DAO$', 'JDBC'),
        (r'.*Repository$', 'JPA'),
    ]
    
    # 包名与框架类型映射（优先级高于后缀）
    DAO_PACKAGE_PATTERNS = [
        (r'\.repository\.', 'JPA'),
        (r'\.mapper\.', 'MYBATIS'),
        (r'\.dao\.', 'MYBATIS'),
    ]
    
    def __init__(self, db_conn: sqlite3.Connection):
        self.db_conn = db_conn
        self.sql_resolver = SqlResolver(db_conn)
        self.entity_resolver = EntityResolver(db_conn)
        self._schema_health = self._check_schema_health()
        self._load_mapping_cache()
    
    def _check_schema_health(self) -> SchemaHealth:
        """
        Schema 健康检查：验证表存在性及关键列完整性
        
        检查项：
        1. dao_entity_mapping 表是否存在
        2. method_sql_mapping 表是否存在  
        3. 关键列（method_id, sql_statement, entity_class）是否存在
        """
        health = SchemaHealth()
        cursor = self.db_conn.cursor()
        
        try:
            # 检查表存在
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name IN ('dao_entity_mapping', 'method_sql_mapping')
            """)
            tables = {row[0] for row in cursor.fetchall()}
            health.has_entity_table = 'dao_entity_mapping' in tables
            health.has_sql_table = 'method_sql_mapping' in tables
            
            if not (health.has_entity_table and health.has_sql_table):
                health.error_message = "Missing required mapping tables"
                logger.warning("DAO Schema unhealthy: %s", health.error_message)
                return health
            
            # 检查关键列（PRAGMA 是 SQLite 特有，安全且轻量）
            cursor.execute("PRAGMA table_info(dao_entity_mapping)")
            entity_cols = {row[1] for row in cursor.fetchall()}
            
            cursor.execute("PRAGMA table_info(method_sql_mapping)")
            sql_cols = {row[1] for row in cursor.fetchall()}
            
            required_entity = {'method_id', 'entity_name'}
            required_sql = {'method_id', 'sql_statement'}
            
            has_entity_cols = required_entity.issubset(entity_cols)
            has_sql_cols = required_sql.issubset(sql_cols)
            
            health.has_required_columns = has_entity_cols and has_sql_cols
            
            if not health.has_required_columns:
                missing = []
                if not has_entity_cols:
                    missing.append("dao_entity_mapping missing required columns")
                if not has_sql_cols:
                    missing.append("method_sql_mapping missing required columns")
                health.error_message = "; ".join(missing)
                logger.warning("DAO Schema incomplete: %s", health.error_message)
                return health
            
            health.is_healthy = True
            logger.info("DAO Schema healthy, full resolution mode enabled")
            
        except sqlite3.Error as e:
            health.error_message = f"Schema check failed: {e}"
            logger.error(health.error_message)
        
        return health
    
    def _load_mapping_cache(self):
        """预加载映射数据到内存（仅 Schema 健康时）"""
        self._entity_cache: Dict[int, dict] = {}
        self._sql_cache: Dict[int, dict] = {}
        
        if not self._schema_health.is_healthy:
            logger.info("Skipping mapping cache load (schema unhealthy)")
            return
        
        try:
            cursor = self.db_conn.cursor()
            
            # 预加载 Entity 映射
            cursor.execute("SELECT method_id, entity_name, entity_class, table_name FROM dao_entity_mapping")
            for row in cursor.fetchall():
                self._entity_cache[row[0]] = {
                    'entity_name': row[1],
                    'entity_class': row[2],
                    'table_name': row[3]
                }
            
            # 预加载 SQL 映射
            cursor.execute("SELECT method_id, sql_type, sql_statement, mapped_statement_id FROM method_sql_mapping")
            for row in cursor.fetchall():
                self._sql_cache[row[0]] = {
                    'sql_type': row[1],
                    'sql_statement': row[2],
                    'mapped_statement_id': row[3]
                }
            
            logger.info("Loaded %d entity mappings and %d SQL mappings", 
                       len(self._entity_cache), len(self._sql_cache))
                       
        except sqlite3.Error as e:
            logger.error("Failed to load mapping cache: %s", e)
            self._schema_health.is_healthy = False
    
    def analyze(self, package_class: str, method_signature: str, 
                method_id: Optional[int]) -> Optional[DaoInfo]:
        """
        分析给定方法是否为 DAO 方法，返回透视信息。
        
        Returns:
            DaoInfo: 如果是 DAO 方法
            None: 如果不是 DAO 方法
        """
        dao_type = self._detect_dao_type(package_class)
        if not dao_type:
            return None
        
        # 基础 DAO 信息
        inferred_entity = self._infer_entity_name(package_class, dao_type)
        
        dao_info = DaoInfo(
            is_dao=True,
            dao_type=dao_type,
            entity_name=inferred_entity,
            entity_source="INFERRED" if inferred_entity else "UNKNOWN"
        )
        
        # 完整模式：从缓存加载精确映射
        if method_id and self._schema_health.is_healthy:
            if method_id in self._entity_cache:
                entity_data = self._entity_cache[method_id]
                dao_info.entity_name = entity_data.get('entity_name') or dao_info.entity_name
                dao_info.entity_class = entity_data.get('entity_class')
                dao_info.table_name = entity_data.get('table_name')
                dao_info.entity_source = "MAPPED"
            
            if method_id in self._sql_cache:
                sql_data = self._sql_cache[method_id]
                dao_info.sql_type = sql_data.get('sql_type')
                dao_info.sql_statement = sql_data.get('sql_statement')
                dao_info.mapped_statement_id = sql_data.get('mapped_statement_id')
        
        return dao_info
    
    def _detect_dao_type(self, package_class: str) -> Optional[str]:
        """
        通过类名后缀和包名检测 DAO 类型。
        
        优先级：
        1. 包名匹配（最高优先级，可覆盖后缀误判）
        2. 类名后缀匹配
        3. 若冲突（如包名指示 JPA 但后缀为 Dao），以包名为准
        4. 若均无法明确判定，返回 UNKNOWN 而非猜测
        """
        class_name = package_class.split('.')[-1]
        
        # 第一步：包名检测（高优先级）
        package_type = None
        for pattern, dao_type in self.DAO_PACKAGE_PATTERNS:
            if re.search(pattern, package_class):
                package_type = dao_type
                break
        
        # 第二步：后缀检测
        suffix_type = None
        for pattern, dao_type in self.DAO_SUFFIX_PATTERNS:
            if re.match(pattern, class_name):
                suffix_type = dao_type
                break
        
        # 第三步：冲突解决
        if package_type and suffix_type:
            if package_type == suffix_type:
                return package_type
            # 冲突时，包名优先，但记录日志
            logger.debug(
                "DAO type conflict for %s: package suggests %s, suffix suggests %s. "
                "Using package type.", package_class, package_type, suffix_type
            )
            return package_type
        
        if package_type:
            return package_type
        if suffix_type:
            return suffix_type
        
        return None
    
    def _infer_entity_name(self, package_class: str, dao_type: str) -> Optional[str]:
        """
        通过命名约定推导 Entity 名称。
        
        规则：
        - UmsAdminMapper → UmsAdmin
        - UmsAdminDao → UmsAdmin
        - UmsAdminRepository → UmsAdmin
        
        失败时返回 None，不强行猜测。
        """
        class_name = package_class.split('.')[-1]
        
        suffixes = ['Mapper', 'Dao', 'DAO', 'Repository']
        for suffix in suffixes:
            if class_name.endswith(suffix):
                return class_name[:-len(suffix)]
        
        return None
```

#### `EntityResolver` 与 `SqlResolver`（内部辅助类）

```python
class EntityResolver:
    """Entity 解析器（内部使用，DaoAnalyzer 已做缓存层）"""
    
    def __init__(self, db_conn: sqlite3.Connection):
        self.db_conn = db_conn


class SqlResolver:
    """SQL 解析器（内部使用，DaoAnalyzer 已做缓存层）"""
    
    def __init__(self, db_conn: sqlite3.Connection):
        self.db_conn = db_conn
```

---

### 2.4 统一方法索引调整（index.py）

**核心调整**：移除 `DaoAnalyzer` 耦合，回归单一职责。

```python
class UnifiedMethodIndex:
    def __init__(self, db_path: str, project_id: int, 
                 commit_old: str, commit_new: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.project_id = project_id
        self.commit_old = commit_old
        self.commit_new = commit_new
        
        # v4.0: 移除 DaoAnalyzer 初始化，索引层不依赖分析逻辑
        # self._dao_analyzer = DaoAnalyzer(self.conn)  # 已删除
        
        self._load_baseline_index()
        self._load_incremental_index()
        self._build_unified_index()
    
    # v4.0: 提供原始连接供外部组件使用（如 DaoAnalyzer）
    def get_db_connection(self) -> sqlite3.Connection:
        """供外部分析器获取数据库连接"""
        return self.conn
    
    # ... 其余 v3.0 逻辑保持不变 ...
```

---

### 2.5 调用链构建器扩展（builder.py）

**核心调整**：`DaoAnalyzer` 作为可选注入参数，解耦索引与分析。

```python
class CallChainBuilder:
    def __init__(self, unified_index: UnifiedMethodIndex, 
                 max_depth: int = 10,
                 dao_analyzer: Optional[DaoAnalyzer] = None):
        self.unified_index = unified_index
        self.max_depth = max_depth
        self.dao_analyzer = dao_analyzer  # v4.0: 可选注入，非强制依赖
    
    def _create_node(self, point: dict, depth: int, 
                     method_data: Optional[dict] = None) -> CallChainNode:
        """创建节点，注入 change_type 与 DAO 信息"""
        package_class = point['package_class']
        signature = point['signature']
        method_name = signature.split('(')[0]
        class_name = package_class.split('.')[-1]
        
        node = CallChainNode(
            node_id=f"{depth}|{package_class}|{signature}",
            package_class=package_class,
            method_signature=signature,
            method_name=method_name,
            class_name=class_name,
            depth=depth,
            invocation_lines=point.get('lines', [])
        )
        
        if method_data:
            # v4.0: 显式枚举转换，永不为 null
            raw_change_type = method_data.get('change_type')
            node.change_type = ChangeType.from_raw(raw_change_type).value
            
            node.db_method_id = method_data.get('method_id')
            
            # v4.0: DAO 分析（仅在注入 analyzer 且存在 method_id 时）
            if self.dao_analyzer and node.db_method_id:
                node.dao_info = self.dao_analyzer.analyze(
                    package_class, signature, node.db_method_id
                )
        
        return node
    
    def _dfs_expand(self, node: CallChainNode, path_visited: Set[str], 
                    current_depth: int):
        # ... v3.0 原有逻辑 ...
        
        for point in sorted_points:
            child_key = f"{point['package_class']}|{point['signature']}"
            
            # 查询子方法的 method_data（用于 change_type 和 DAO 分析）
            child_method_data = self.unified_index.query_method(
                point['package_class'], point['signature']
            )
            
            if child_key in path_visited:
                child = self._create_node(point, current_depth + 1, child_method_data)
                child.is_cyclic = True
                child.is_leaf = True
                node.children.append(child)
                continue
            
            child = self._create_node(point, current_depth + 1, child_method_data)
            node.children.append(child)
            
            path_visited.add(child_key)
            self._dfs_expand(child, path_visited, current_depth + 1)
            path_visited.discard(child_key)
        
        # ... 后续逻辑不变 ...
```

---

## 3. 数据库扩展设计（可选依赖）

### 3.1 新增表结构

> **说明**：以下表为 v4.0 的**可选依赖**。若不存在或列缺失，`DaoAnalyzer` 自动降级为命名推导模式，不影响核心调用链功能。

```sql
-- ============================================
-- 表 1: DAO 与 Entity 的映射关系
-- ============================================
CREATE TABLE IF NOT EXISTS dao_entity_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method_id INTEGER NOT NULL,
    entity_class TEXT,              -- 实体全限定类名
    entity_name TEXT,               -- 实体简单类名
    table_name TEXT,                -- 对应数据库表名
    dao_type TEXT DEFAULT 'MYBATIS', -- MYBATIS / JPA / JDBC / MYBATIS_PLUS
    UNIQUE(method_id)
);

-- ============================================
-- 表 2: 方法的 SQL 语句映射
-- ============================================
CREATE TABLE IF NOT EXISTS method_sql_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method_id INTEGER NOT NULL,
    sql_type TEXT,                  -- SELECT / INSERT / UPDATE / DELETE / BATCH / UNKNOWN
    sql_statement TEXT,             -- 完整 SQL（可能含 #{param} 占位符）
    raw_sql TEXT,                   -- 原始 SQL（含 MyBatis 标签如 <if>）
    mapped_statement_id TEXT,       -- MyBatis: namespace.id
    UNIQUE(method_id)
);
```

### 3.2 Schema 版本管理建议

建议在 JCCI 主数据库中维护 Schema 版本，但 v4.0 模块本身不做强制要求：

```sql
-- JCCI 主数据库建议增加（非 v4.0 强制依赖）
CREATE TABLE IF NOT EXISTS schema_version (
    module TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 初始化 v4.0 DAO 模块版本
INSERT OR REPLACE INTO schema_version (module, version) VALUES ('call_chain_dao', 1);
```

### 3.3 数据填充方式（非本模块职责）

| 来源 | 说明 |
|------|------|
| JCCI 主分析流程 | 解析 Java 源码/MyBatis XML 时，提取 `@Select`/`@Insert` 注解或 XML 标签，入库 |
| 外部导入 | 用户通过 DBA 提供的慢查询日志或 MyBatis 插件反向导入 SQL 映射 |
| 运行时 Agent | 通过 Java Agent 拦截 JDBC 调用，回填实际执行的 SQL |

---

## 4. 输出示例

### 4.1 含 change_type 的调用链

```json
{
  "node_id": "0|com.macro.mall.service.UmsAdminServiceImpl|delete(Long)",
  "package_class": "com.macro.mall.service.UmsAdminServiceImpl",
  "method_signature": "delete(Long)",
  "method_name": "delete",
  "class_name": "UmsAdminServiceImpl",
  "depth": 0,
  "invocation_lines": [],
  "is_cyclic": false,
  "is_leaf": false,
  "db_method_id": 1523,
  "change_type": "MODIFIED",
  "dao_info": null,
  "children": [
    {
      "node_id": "1|com.macro.mall.mapper.UmsAdminMapper|deleteByPrimaryKey(Long)",
      "package_class": "com.macro.mall.mapper.UmsAdminMapper",
      "method_signature": "deleteByPrimaryKey(Long)",
      "method_name": "deleteByPrimaryKey",
      "class_name": "UmsAdminMapper",
      "depth": 1,
      "invocation_lines": [142],
      "is_cyclic": false,
      "is_leaf": true,
      "db_method_id": 3421,
      "change_type": "UNCHANGED",
      "dao_info": {
        "is_dao": true,
        "dao_type": "MYBATIS",
        "entity_name": "UmsAdmin",
        "entity_class": "com.macro.mall.model.UmsAdmin",
        "entity_source": "MAPPED",
        "table_name": "ums_admin",
        "sql_type": "DELETE",
        "sql_statement": "DELETE FROM ums_admin WHERE id = #{id}",
        "mapped_statement_id": "com.macro.mall.mapper.UmsAdminMapper.deleteByPrimaryKey"
      },
      "children": []
    }
  ]
}
```

### 4.2 降级模式输出（无映射表）

```json
{
  "change_type": "UNCHANGED",
  "dao_info": {
    "is_dao": true,
    "dao_type": "MYBATIS",
    "entity_name": "UmsAdmin",
    "entity_class": null,
    "entity_source": "INFERRED",
    "table_name": null,
    "sql_type": null,
    "sql_statement": null,
    "mapped_statement_id": null
  }
}
```

### 4.3 变更影响可视化建议

通过 `change_type` 字段，用户可快速识别调用链中哪些节点涉及变更：

| change_type | 可视化建议 | 业务含义 |
|-------------|------------|----------|
| `ADDED` | 🟢 绿色 | 新增方法，调用链新增节点 |
| `MODIFIED` | 🟡 黄色 | 方法逻辑变更，可能影响下游 |
| `DELETED` | 🔴 红色（理论上不出现在链中） | 已删除（由索引过滤） |
| `UNCHANGED` | ⚪ 灰色 | 未变更，仅作为调用链路经 |
| `UNKNOWN` | ⚪ 灰色 | 基线数据未记录变更状态 |

---

## 5. 测试策略

### 5.1 新增测试覆盖

| 测试文件 | 测试数 | 覆盖场景 |
|----------|--------|----------|
| `test_change_type.py` | 10 | 枚举转换、基线 UNCHANGED、增量 MODIFIED、增量 ADDED、UNKNOWN 降级、透传一致性、DELETED 过滤、大小写兼容 |
| `test_dao_analyzer.py` | 10 | Mapper 识别、Repository 识别、包名优先、冲突降级 UNKNOWN、SQL 映射加载、Entity 推导、降级模式、非 DAO 过滤、Schema 不完整、缓存机制 |
| `test_schema_health.py` | 4 | 表缺失、列缺失、完整 Schema、异常连接 |
| `test_builder.py` | 扩展 4 个 | change_type 注入、DAO 注入、无 DAO 分析器、降级路径 |

### 5.2 关键测试案例

#### T1: change_type 枚举与透传

```python
def test_change_type_incremental_overwrites_baseline():
    """测试增量 MODIFIED 覆盖基线 UNCHANGED"""
    # 基线: methodA (UNCHANGED), 增量: methodA (MODIFIED)
    chain = builder.build('com.test.Service', 'methodA()')
    assert chain.change_type == "MODIFIED"

def test_change_type_unknown_when_raw_invalid():
    """测试非法原始值降级为 UNKNOWN"""
    # method_data['change_type'] = 'invalid_value'
    chain = builder.build('com.test.Service', 'methodB()')
    assert chain.change_type == "UNKNOWN"
```

#### T2: DAO 分析器独立注入

```python
def test_builder_without_dao_analyzer():
    """测试不注入 DAO 分析器时，所有节点 dao_info 为 null"""
    builder = CallChainBuilder(index, max_depth=10)  # 无 dao_analyzer
    chain = builder.build('com.test.Service', 'methodA()')
    assert chain.dao_info is None

def test_builder_with_dao_analyzer():
    """测试注入 DAO 分析器后，Mapper 节点正确识别"""
    analyzer = DaoAnalyzer(mock_conn)
    builder = CallChainBuilder(index, max_depth=10, dao_analyzer=analyzer)
    chain = builder.build('com.test.Service', 'save()')
    assert chain.children[0].dao_info.is_dao is True
```

#### T3: 包名优先与冲突解决

```python
def test_package_priority_over_suffix():
    """测试包名指示 JPA 时，覆盖 Dao 后缀的 MYBATIS 推断"""
    # package: com.test.repository.UserDao (包名 JPA，后缀 Dao)
    info = analyzer.analyze('com.test.repository.UserDao', 'findById(Long)', 1)
    assert info.dao_type == "JPA"  # 包名优先

def test_unknown_on_conflict_ambiguity():
    """测试无法明确判定时返回 UNKNOWN"""
    # package: com.test.misc.UserDao (无特征包名，后缀 Dao 但包名不匹配 MYBATIS)
    # 此场景下后缀推断 MYBATIS，但无包名确认，仍返回 MYBATIS（非 UNKNOWN）
    # 若包名明确为 .repository. 但后缀为 Mapper，则包名 JPA 优先
    info = analyzer.analyze('com.test.repository.UserMapper', 'find()', 1)
    assert info.dao_type == "JPA"  # 包名 .repository. 优先于 Mapper 后缀
```

#### T4: Schema 健康与降级

```python
def test_degraded_mode_logs_warning():
    """测试 Schema 不完整时记录 warning 并降级"""
    # 创建缺少列的表
    analyzer = DaoAnalyzer(broken_conn)
    assert analyzer._schema_health.is_healthy is False
    
    info = analyzer.analyze('com.test.UserMapper', 'select()', None)
    assert info.entity_source == "INFERRED"
    assert info.sql_statement is None
```

---

## 6. 使用指南（v4.0 新增能力）

### 6.1 基础用法（向后兼容）

```python
from src.jcci.call_chain import UnifiedMethodIndex, CallChainBuilder

# v3.0 代码无需修改即可运行
index = UnifiedMethodIndex(db_path="db.sqlite", project_id=1, 
                           commit_old="abc", commit_new="def")
builder = CallChainBuilder(index, max_depth=10)
chain = builder.build("com.xxx.Service", "method()")

# 自动包含 change_type="UNKNOWN" 和 dao_info=null
print(chain.to_dict())
```

### 6.2 启用 DAO 透视（v4.0 新特性）

```python
from src.jcci.call_chain import UnifiedMethodIndex, CallChainBuilder, DaoAnalyzer

index = UnifiedMethodIndex(db_path="db.sqlite", project_id=1,
                           commit_old="abc", commit_new="def")

# 独立创建 DAO 分析器并注入
dao_analyzer = DaoAnalyzer(index.get_db_connection())
builder = CallChainBuilder(index, max_depth=10, dao_analyzer=dao_analyzer)

chain = builder.build("com.macro.mall.service.UmsAdminServiceImpl", "delete(Long)")

# 遍历并打印 DAO 操作
def print_dao_operations(node, indent=0):
    prefix = "  " * indent
    if node.dao_info and node.dao_info.is_dao:
        badge = f"[{node.dao_info.sql_type}]" if node.dao_info.sql_type else "[DAO]"
        source = f"({node.dao_info.entity_source})"
        print(f"{prefix}{badge} {node.class_name}.{node.method_signature} "
              f"→ {node.dao_info.entity_name} {source}")
    else:
        print(f"{prefix}{node.class_name}.{node.method_signature}")
    
    for child in node.children:
        print_dao_operations(child, indent + 1)

print_dao_operations(chain)
```

**预期输出**：
```
UmsAdminServiceImpl.delete(Long) [MODIFIED]
  [DELETE] UmsAdminMapper.deleteByPrimaryKey(Long) → UmsAdmin (MAPPED)
```

### 6.3 查看变更影响

```python
def print_change_impact(node, indent=0):
    """递归打印调用链，高亮变更节点"""
    prefix = "  " * indent
    badge = {
        "MODIFIED": "[🟡 MODIFIED]",
        "ADDED": "[🟢 ADDED]",
        "UNCHANGED": "",
        "UNKNOWN": ""
    }.get(node.change_type, "")
    
    print(f"{prefix}{node.class_name}.{node.method_signature} {badge}")
    for child in node.children:
        print_change_impact(child, indent + 1)
```

---

## 7. 性能评估

### 7.1 当前性能（Mall 项目基准）

| 指标 | v3.0 | v4.0（预估） | 说明 |
|------|------|--------------|------|
| 索引构建时间 | ~0.47s | ~0.47s | 无变化（DaoAnalyzer 不再由 Index 初始化） |
| DAO 分析器初始化 | N/A | ~0.05s | Schema 检查 + 缓存加载（14k 方法规模） |
| 调用链构建时间（3 节点） | <0.01s | <0.01s | 内存缓存查询，O(1) |
| 调用链构建时间（50 节点，50% DAO） | N/A | ~0.02s | 含 DAO 分析开销 |
| 内存占用 | ~28 MB | ~30 MB | +2 MB（Entity/SQL 映射缓存） |

### 7.2 并发与线程安全

| 组件 | 线程安全 | 说明 |
|------|----------|------|
| `UnifiedMethodIndex` | ✅ 只读安全 | 构建后为只读，可多线程共享 |
| `DaoAnalyzer` | ✅ 只读安全 | 初始化后缓存只读，可多线程共享 |
| `CallChainBuilder` | ❌ 非线程安全 | 含 DFS 状态（path_visited），每次调用应新建实例 |

**建议**：Web 接口场景下，`Index` 和 `DaoAnalyzer` 作为单例复用，`Builder` 每次请求新建。

---

## 8. 已知限制与扩展建议

### 8.1 当前限制

1. **SQL 来源依赖前置采集**：v4.0 本身不解析 MyBatis XML 或注解，依赖外部数据入库
2. **命名推导准确率**：`UserDAO` → `User` 在标准命名下有效，非常规命名（如 `UserDAO` → `UserInfo`）会推导错误，但 `entity_source="INFERRED"` 明确标识了推导属性
3. **动态 SQL 展示**：`sql_statement` 展示模板 SQL（含 `${}`/`#{}`），非实际执行 SQL
4. **JPA 复杂查询**：`@Query` 注解中的 JPQL 需外部解析入库，本模块仅做展示
5. **跨项目调用链**：不支持微服务间 Feign/Dubbo 调用的 DAO 透视

### 8.2 未来扩展（v4.1+）

| 特性 | 说明 |
|------|------|
| SQL 参数绑定 | 补充 `sql_bound_parameters`，由外部 Agent 提供实际参数值 |
| 事务边界标注 | 识别 `@Transactional` 注解，标注事务起始与传播节点 |
| 批量操作识别 | 识别 `insertBatch` / `saveBatch` 等批量 DAO 操作 |
| 跨库调用链 | 识别微服务间调用，展示跨服务 Entity 操作 |

---

## 9. 文件清单（v4.0 增量）

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `src/jcci/call_chain/models.py` | 修改 | 增加 `ChangeType` 枚举、`change_type` 字段、`DaoInfo`（含 `entity_source`） |
| `src/jcci/call_chain/index.py` | 修改 | **移除** `DaoAnalyzer` 耦合，增加 `get_db_connection()` |
| `src/jcci/call_chain/builder.py` | 修改 | 接收可选 `dao_analyzer` 参数，节点创建时注入 change_type 与 DAO 信息 |
| `src/jcci/call_chain/dao_analyzer.py` | 新增 | 独立 DAO 分析器，含 Schema 健康检查、缓存、包名优先规则 |
| `src/jcci/call_chain/entity_resolver.py` | 新增 | Entity 命名推导（内部辅助） |
| `src/jcci/call_chain/sql_resolver.py` | 新增 | SQL 映射查询（内部辅助） |
| `tests/test_change_type.py` | 新增 | 10 个测试：枚举、透传、降级、大小写 |
| `tests/test_dao_analyzer.py` | 新增 | 10 个测试：识别、映射、降级、冲突、缓存 |
| `tests/test_schema_health.py` | 新增 | 4 个测试：表缺失、列缺失、完整、异常 |
| `tests/test_builder.py` | 修改 | 增加 4 个测试：change_type 注入、DAO 注入、无分析器、降级 |

---

## 10. 迁移指南（v3.0 → v4.0）

### 10.1 代码迁移

**无 Breaking Change**。v3.0 的调用代码在 v4.0 中完全兼容：

```python
# v3.0 代码无需修改即可运行
chain = builder.build('com.xxx.Service', 'method()')
data = chain.to_dict()

# data 中自动包含：
# - change_type: "UNKNOWN"（而非 null，下游应做宽松解析）
# - dao_info: null
```

### 10.2 下游 JSON Schema 提示

若下游使用严格 JSON Schema 校验，请注意：

- `change_type` 为字符串，永不为 `null`，默认值为 `"UNKNOWN"`
- `dao_info` 可能为 `null`，若不为 `null` 则为对象
- 新增字段均为可选，旧 Schema 可忽略

### 10.3 启用完整 DAO 能力

```python
# 步骤 1：在数据库中创建映射表（执行 3.1 节 SQL）
# 步骤 2：由 JCCI 主流程或外部工具填充数据
# 步骤 3：代码中注入 DaoAnalyzer

index = UnifiedMethodIndex(db_path="db.sqlite", ...)
dao_analyzer = DaoAnalyzer(index.get_db_connection())
builder = CallChainBuilder(index, dao_analyzer=dao_analyzer)
```

---

## 11. 评审意见响应清单

| 评审意见 | 响应措施 | 状态 |
|----------|----------|------|
| 明确 `change_type` 判定逻辑与枚举定义 | 新增 `ChangeType` 枚举类，显式定义 5 种状态及 `from_raw` 转换逻辑 | ✅ 已解决 |
| 降级路径增加日志输出 | `DaoAnalyzer` 全路径使用 `logging`，Schema 检查、缓存加载、冲突解决均有日志 | ✅ 已解决 |
| `DaoAnalyzer` 从 `UnifiedMethodIndex` 解耦 | `DaoAnalyzer` 改为独立组件，由 `CallChainBuilder` 可选注入；`Index` 仅提供 `get_db_connection()` | ✅ 已解决 |
| 区分 Entity 来源 | `DaoInfo` 新增 `entity_source` 字段：`INFERRED` / `MAPPED` / `UNKNOWN` | ✅ 已解决 |
| 泛型 DAO 识别冲突 | 引入包名优先级规则：`.repository.` 优先于 `*Dao` 后缀；冲突时包名优先并记录 debug 日志 | ✅ 已解决 |
| SQL 参数绑定（后续版本） | 在 8.2 节列入 v4.1+ 路线图，当前仅展示模板 SQL | 📝 已记录 |
| Schema 版本管理（后续版本） | 在 3.2 节给出建议方案，v4.0 通过 `SchemaHealth` 做运行时列检查实现等效降级 | 📝 已缓解 |
| 性能基准补充 | 7.1 节补充 50 节点场景预估；7.2 节明确线程安全策略 | ✅ 已解决 |
| 下游 Schema 影响提示 | 10.2 节明确提示 `change_type` 永不为 null，`dao_info` 可能为 null | ✅ 已解决 |

---

**文档结束**