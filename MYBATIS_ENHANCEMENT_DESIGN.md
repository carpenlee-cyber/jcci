# MyBatis Mapper 增强功能设计方案

**版本**: v1.0  
**日期**: 2026-05-11  
**状态**: 设计中

---

## 📋 功能概览

本次实施包含三个P2/P3优先级的增强功能：

1. **SQL性能分析** - 自动检测慢查询模式和性能问题
2. **数据血缘追踪** - 字段级依赖关系追踪
3. **可视化增强** - SQL节点高亮和交互优化

---

## 1️⃣ SQL性能分析器设计

### 1.1 架构设计

```
┌─────────────────────────────────────────┐
│      SqlPerformanceAnalyzer             │
├─────────────────────────────────────────┤
│                                         │
│  • detect_slow_queries()                │
│  • detect_n_plus_one()                  │
│  • check_index_usage()                  │
│  • suggest_optimization()               │
│                                         │
└──────────┬──────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────┐
│      PerformanceRule Engine             │
├─────────────────────────────────────────┤
│                                         │
│  Rules:                                 │
│  • FullTableScanRule                    │
│  • SelectStarRule                       │
│  • LikeWildcardRule                     │
│  • NestedSubqueryRule                   │
│  • OrConditionRule                      │
│  • NPlusOneQueryRule                    │
│                                         │
└─────────────────────────────────────────┘
```

### 1.2 核心类设计

#### `SqlPerformanceAnalyzer`
```python
class SqlPerformanceAnalyzer:
    """SQL性能分析器"""
    
    def __init__(self, db_schema=None):
        """
        Args:
            db_schema: 数据库schema信息（可选，用于索引检查）
        """
        self.db_schema = db_schema
        self.rules = self._load_rules()
    
    def analyze(self, sql_info: dict) -> PerformanceReport:
        """
        分析SQL语句的性能问题
        
        Args:
            sql_info: SQL信息字典
                {
                    'sql_type': 'SELECT',
                    'sql_content': 'SELECT * FROM ...',
                    'tables': ['ums_menu'],
                    'mapper_method': 'com.test.Mapper.select'
                }
        
        Returns:
            PerformanceReport: 性能报告
        """
        report = PerformanceReport()
        
        # 应用所有规则
        for rule in self.rules:
            issues = rule.check(sql_info)
            report.add_issues(issues)
        
        # 计算风险评分
        report.calculate_score()
        
        return report
    
    def detect_n_plus_one(self, call_chain: CallChainNode) -> List[NPlusOneIssue]:
        """
        检测N+1查询问题
        
        Args:
            call_chain: 调用链根节点
        
        Returns:
            N+1问题列表
        """
        issues = []
        self._traverse_for_n_plus_one(call_chain, [], issues)
        return issues
```

#### `PerformanceRule` (基类)
```python
class PerformanceRule(ABC):
    """性能规则基类"""
    
    @abstractmethod
    def check(self, sql_info: dict) -> List[PerformanceIssue]:
        """检查SQL是否存在性能问题"""
        pass
    
    @property
    @abstractmethod
    def rule_name(self) -> str:
        """规则名称"""
        pass
    
    @property
    @abstractmethod
    def severity(self) -> str:
        """严重程度: HIGH/MEDIUM/LOW"""
        pass
```

#### 具体规则示例

```python
class FullTableScanRule(PerformanceRule):
    """全表扫描检测规则"""
    
    @property
    def rule_name(self):
        return "FULL_TABLE_SCAN"
    
    @property
    def severity(self):
        return "HIGH"
    
    def check(self, sql_info: dict):
        issues = []
        sql = sql_info['sql_content'].upper()
        
        # 检测SELECT无WHERE条件
        if sql_info['sql_type'] == 'SELECT':
            if 'WHERE' not in sql and 'LIMIT' not in sql:
                issues.append(PerformanceIssue(
                    rule=self.rule_name,
                    severity=self.severity,
                    message=f"⚠️ 全表扫描: SELECT语句缺少WHERE或LIMIT条件",
                    suggestion="添加WHERE条件或LIMIT子句限制返回行数",
                    affected_tables=sql_info['tables']
                ))
        
        return issues


class SelectStarRule(PerformanceRule):
    """SELECT * 检测规则"""
    
    @property
    def rule_name(self):
        return "SELECT_STAR"
    
    @property
    def severity(self):
        return "MEDIUM"
    
    def check(self, sql_info: dict):
        issues = []
        sql = sql_info['sql_content']
        
        # 检测 SELECT *
        if re.search(r'SELECT\s+\*', sql, re.IGNORECASE):
            issues.append(PerformanceIssue(
                rule=self.rule_name,
                severity=self.severity,
                message=f"⚠️ 使用SELECT *: 建议明确指定需要的列",
                suggestion="替换为具体的列名，如 SELECT id, name FROM ...",
                affected_tables=sql_info['tables']
            ))
        
        return issues


class LikeWildcardRule(PerformanceRule):
    """LIKE通配符检测规则"""
    
    @property
    def rule_name(self):
        return "LIKE_WILDCARD"
    
    @property
    def severity(self):
        return "HIGH"
    
    def check(self, sql_info: dict):
        issues = []
        sql = sql_info['sql_content']
        
        # 检测 LIKE '%...%'
        if re.search(r"LIKE\s+'%", sql, re.IGNORECASE):
            issues.append(PerformanceIssue(
                rule=self.rule_name,
                severity=self.severity,
                message=f"⚠️ LIKE前缀通配符: 无法使用索引，性能差",
                suggestion="考虑使用全文索引或调整查询逻辑",
                affected_tables=sql_info['tables']
            ))
        
        return issues
```

#### `PerformanceReport`
```python
@dataclass
class PerformanceIssue:
    """性能问题"""
    rule: str
    severity: str  # HIGH/MEDIUM/LOW
    message: str
    suggestion: str
    affected_tables: List[str]


@dataclass
class PerformanceReport:
    """性能报告"""
    issues: List[PerformanceIssue] = field(default_factory=list)
    score: int = 100  # 性能评分 (0-100, 越高越好)
    
    def add_issues(self, issues: List[PerformanceIssue]):
        self.issues.extend(issues)
    
    def calculate_score(self):
        """计算性能评分"""
        penalty = 0
        for issue in self.issues:
            if issue.severity == 'HIGH':
                penalty += 20
            elif issue.severity == 'MEDIUM':
                penalty += 10
            else:
                penalty += 5
        
        self.score = max(0, 100 - penalty)
    
    @property
    def level(self) -> str:
        """性能等级"""
        if self.score >= 90:
            return "EXCELLENT"
        elif self.score >= 70:
            return "GOOD"
        elif self.score >= 50:
            return "FAIR"
        else:
            return "POOR"
```

### 1.3 N+1查询检测算法

```python
def _traverse_for_n_plus_one(
    self, 
    node: CallChainNode, 
    path: List[CallChainNode],
    issues: List[NPlusOneIssue]
):
    """
    遍历调用链检测N+1查询
    
    检测逻辑：
    1. 识别循环结构（for/while）
    2. 检查循环内是否有Mapper调用
    3. 标记为N+1问题
    """
    current_path = path + [node]
    
    # 检测当前节点是否为循环
    if self._is_loop_node(node):
        # 检查循环内的子节点
        mapper_calls = []
        for child in node.children:
            if self._is_mapper_call(child):
                mapper_calls.append(child)
        
        if len(mapper_calls) > 0:
            issues.append(NPlusOneIssue(
                loop_node=node,
                mapper_calls=mapper_calls,
                message=f"⚠️ N+1查询: 循环内执行{len(mapper_calls)}次数据库查询",
                suggestion="使用批量查询替代循环查询"
            ))
    
    # 递归遍历子节点
    for child in node.children:
        self._traverse_for_n_plus_one(child, current_path, issues)
```

---

## 2️⃣ 数据血缘追踪器设计

### 2.1 架构设计

```
┌─────────────────────────────────────────┐
│      FieldLineageTracker                │
├─────────────────────────────────────────┤
│                                         │
│  • track_field_sources()                │
│  • track_field_consumers()              │
│  • build_lineage_graph()                │
│  • analyze_impact()                     │
│                                         │
└──────────┬──────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────┐
│      LineageGraph (NetworkX)            │
├─────────────────────────────────────────┤
│                                         │
│  Nodes:                                 │
│  • TABLE.field                          │
│  • METHOD                               │
│  • API_ENDPOINT                         │
│                                         │
│  Edges:                                 │
│  • READS                                │
│  • WRITES                               │
│  • TRANSFORMS                           │
│                                         │
└─────────────────────────────────────────┘
```

### 2.2 核心类设计

#### `FieldLineageTracker`
```python
class FieldLineageTracker:
    """字段血缘追踪器"""
    
    def __init__(self, db_helper: SqliteHelper, project_id: int):
        self.db = db_helper
        self.project_id = project_id
        self.lineage_graph = nx.DiGraph()
    
    def track_from_sql(self, sql_info: dict, mapper_method: str) -> FieldLineage:
        """
        从SQL语句追踪字段血缘
        
        Args:
            sql_info: SQL信息
            mapper_method: Mapper方法名
        
        Returns:
            FieldLineage: 字段血缘信息
        """
        lineage = FieldLineage()
        
        # 解析SQL提取字段
        fields = self._extract_fields_from_sql(sql_info)
        
        for field in fields:
            if sql_info['sql_type'] in ['INSERT', 'UPDATE']:
                # 写入操作
                lineage.add_write(field.table, field.column, mapper_method)
            elif sql_info['sql_type'] == 'SELECT':
                # 读取操作
                lineage.add_read(field.table, field.column, mapper_method)
            
            # 添加到图
            self._add_to_graph(field, mapper_method, sql_info['sql_type'])
        
        return lineage
    
    def get_field_sources(self, table: str, column: str) -> List[DataSource]:
        """
        获取字段的来源
        
        Args:
            table: 表名
            column: 列名
        
        Returns:
            数据来源列表
        """
        node_id = f"{table}.{column}"
        sources = []
        
        # 查找所有写入该字段的节点
        for predecessor in self.lineage_graph.predecessors(node_id):
            edge_data = self.lineage_graph.get_edge_data(predecessor, node_id)
            if edge_data['type'] == 'WRITES':
                sources.append(DataSource(
                    type=edge_data['source_type'],
                    path=edge_data['path'],
                    method=predecessor
                ))
        
        return sources
    
    def get_field_consumers(self, table: str, column: str) -> List[DataConsumer]:
        """
        获取字段的使用者
        
        Args:
            table: 表名
            column: 列名
        
        Returns:
            数据使用者列表
        """
        node_id = f"{table}.{column}"
        consumers = []
        
        # 查找所有读取该字段的节点
        for successor in self.lineage_graph.successors(node_id):
            edge_data = self.lineage_graph.get_edge_data(node_id, successor)
            if edge_data['type'] == 'READS':
                consumers.append(DataConsumer(
                    type=edge_data['target_type'],
                    path=edge_data['path'],
                    method=successor
                ))
        
        return consumers
    
    def analyze_impact(self, table: str, column: str) -> ImpactAnalysis:
        """
        分析字段变更的影响范围
        
        Args:
            table: 表名
            column: 列名
        
        Returns:
            ImpactAnalysis: 影响分析报告
        """
        impact = ImpactAnalysis()
        
        # 获取所有消费者
        consumers = self.get_field_consumers(table, column)
        
        # 分类统计
        impact.api_count = len([c for c in consumers if c.type == 'API'])
        impact.report_count = len([c for c in consumers if c.type == 'REPORT'])
        impact.service_count = len([c for c in consumers if c.type == 'SERVICE'])
        
        # 风险评估
        total_impact = impact.api_count + impact.report_count + impact.service_count
        if total_impact > 10:
            impact.risk_level = "HIGH"
        elif total_impact > 5:
            impact.risk_level = "MEDIUM"
        else:
            impact.risk_level = "LOW"
        
        impact.consumers = consumers
        
        return impact
```

#### `FieldLineage`
```python
@dataclass
class FieldInfo:
    """字段信息"""
    table: str
    column: str
    alias: Optional[str] = None  # 别名


@dataclass
class FieldLineage:
    """字段血缘"""
    reads: List[Tuple[str, str, str]] = field(default_factory=list)  # (table, column, method)
    writes: List[Tuple[str, str, str]] = field(default_factory=list)
    
    def add_read(self, table: str, column: str, method: str):
        self.reads.append((table, column, method))
    
    def add_write(self, table: str, column: str, method: str):
        self.writes.append((table, column, method))
```

### 2.3 SQL字段解析

```python
def _extract_fields_from_sql(self, sql_info: dict) -> List[FieldInfo]:
    """
    从SQL中提取字段信息
    
    支持：
    - SELECT col1, col2 FROM table
    - INSERT INTO table (col1, col2) VALUES (...)
    - UPDATE table SET col1 = ?, col2 = ?
    """
    fields = []
    sql = sql_info['sql_content']
    sql_type = sql_info['sql_type']
    tables = sql_info['tables']
    
    if sql_type == 'SELECT':
        # 解析SELECT字段
        select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
        if select_match:
            select_clause = select_match.group(1)
            # 排除 *
            if select_clause.strip() != '*':
                # 分割字段
                for field_str in select_clause.split(','):
                    field_str = field_str.strip()
                    # 处理别名: col AS alias
                    alias_match = re.match(r'(\w+)(?:\s+AS\s+(\w+))?', field_str, re.IGNORECASE)
                    if alias_match:
                        col = alias_match.group(1)
                        alias = alias_match.group(2)
                        # 假设第一个表
                        if tables:
                            fields.append(FieldInfo(tables[0], col, alias))
    
    elif sql_type == 'INSERT':
        # 解析INSERT字段
        insert_match = re.search(r'INSERT\s+INTO\s+\w+\s*\((.*?)\)', sql, re.IGNORECASE)
        if insert_match:
            columns_str = insert_match.group(1)
            for col in columns_str.split(','):
                col = col.strip()
                if tables:
                    fields.append(FieldInfo(tables[0], col))
    
    elif sql_type == 'UPDATE':
        # 解析UPDATE字段
        update_match = re.search(r'UPDATE\s+(\w+)\s+SET\s+(.*?)\s+WHERE', sql, re.IGNORECASE | re.DOTALL)
        if update_match:
            set_clause = update_match.group(2)
            for assignment in set_clause.split(','):
                col = assignment.split('=')[0].strip()
                if tables:
                    fields.append(FieldInfo(tables[0], col))
    
    return fields
```

---

## 3️⃣ 可视化增强设计

### 3.1 SQL节点样式规范

#### 颜色编码
```python
SQL_COLOR_MAP = {
    'SELECT': '#3498db',  # 蓝色
    'INSERT': '#2ecc71',  # 绿色
    'UPDATE': '#f39c12',  # 橙色
    'DELETE': '#e74c3c',  # 红色
}

RISK_COLOR_MAP = {
    'CRITICAL': '#c0392b',  # 深红
    'HIGH': '#e67e22',      # 橙红
    'MEDIUM': '#f1c40f',    # 黄色
    'LOW': '#95a5a6',       # 灰色
}
```

#### 节点图标
```python
SQL_ICON_MAP = {
    'SELECT': '🔍',
    'INSERT': '➕',
    'UPDATE': '✏️',
    'DELETE': '🗑️',
}

RISK_ICON_MAP = {
    'CRITICAL': '🔴',
    'HIGH': '⚠️',
    'MEDIUM': 'ℹ️',
    'LOW': '✅',
}
```

### 3.2 前端数据结构增强

#### 修改 `CallChainNode.to_dict()`
```python
def to_dict(self) -> dict:
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
        "entry_annotation": self.entry_annotation,
        "api_paths": self.api_paths,
        "change_type": self.change_type,
        "dao_info": self.dao_info.to_dict() if self.dao_info else None,
    }
    
    # ✅ 新增：SQL节点增强信息
    if hasattr(self, 'sql_details') and self.sql_details:
        base['sql_enhanced'] = {
            'sql_type': self.sql_details.get('sql_type'),
            'tables': self.sql_details.get('tables', []),
            'risk_level': self.sql_details.get('risk_level', 'LOW'),
            'warning': self.sql_details.get('warning', ''),
            'is_dynamic_sql': self.sql_details.get('is_dynamic_sql', False),
            'performance_score': self.sql_details.get('performance_score', 100),
            'performance_issues': self.sql_details.get('performance_issues', []),
        }
    
    return base
```

### 3.3 前端渲染逻辑

#### Vue组件增强
```javascript
// SqlNodeComponent.vue
<template>
  <div 
    class="sql-node"
    :class="[
      `sql-type-${sqlType.toLowerCase()}`,
      `risk-${riskLevel.toLowerCase()}`
    ]"
    @mouseenter="showTooltip"
    @mouseleave="hideTooltip"
    @click="showDetailModal"
  >
    <span class="sql-icon">{{ sqlIcon }}</span>
    <span class="sql-label">{{ sqlLabel }}</span>
    <span class="risk-badge" v-if="riskLevel !== 'LOW'">
      {{ riskIcon }} {{ riskLevel }}
    </span>
  </div>
</template>

<script>
export default {
  props: {
    node: Object
  },
  computed: {
    sqlType() {
      return this.node.sql_enhanced?.sql_type || 'UNKNOWN'
    },
    riskLevel() {
      return this.node.sql_enhanced?.risk_level || 'LOW'
    },
    sqlIcon() {
      const icons = {
        'SELECT': '🔍',
        'INSERT': '➕',
        'UPDATE': '✏️',
        'DELETE': '🗑️'
      }
      return icons[this.sqlType] || '📊'
    },
    riskIcon() {
      const icons = {
        'CRITICAL': '🔴',
        'HIGH': '⚠️',
        'MEDIUM': 'ℹ️',
        'LOW': '✅'
      }
      return icons[this.riskLevel] || ''
    },
    sqlLabel() {
      const tables = this.node.sql_enhanced?.tables || []
      return `${this.sqlType}: ${tables.join(', ')}`
    }
  },
  methods: {
    showTooltip() {
      // 显示悬停提示
      this.$emit('show-tooltip', {
        title: `${this.sqlIcon} ${this.sqlType} ${this.node.sql_enhanced?.tables.join(', ')}`,
        content: this.buildTooltipContent()
      })
    },
    buildTooltipContent() {
      const details = this.node.sql_enhanced
      return `
        <div class="sql-tooltip">
          <strong>SQL类型:</strong> ${details.sql_type}<br>
          <strong>涉及表:</strong> ${details.tables.join(', ')}<br>
          <strong>风险等级:</strong> <span class="risk-${details.risk_level.toLowerCase()}">${details.risk_level}</span><br>
          <strong>动态SQL:</strong> ${details.is_dynamic_sql ? '是' : '否'}<br>
          ${details.warning ? `<strong>警告:</strong> ${details.warning}<br>` : ''}
          ${details.performance_score < 70 ? `<strong>性能评分:</strong> ${details.performance_score}/100<br>` : ''}
        </div>
      `
    },
    showDetailModal() {
      // 弹出详细信息模态框
      this.$emit('show-detail', this.node)
    }
  }
}
</script>

<style scoped>
.sql-node {
  padding: 8px 12px;
  border-radius: 6px;
  border: 2px solid;
  cursor: pointer;
  transition: all 0.2s;
}

.sql-node:hover {
  transform: scale(1.05);
  box-shadow: 0 4px 8px rgba(0,0,0,0.2);
}

/* SQL类型颜色 */
.sql-type-select {
  background-color: rgba(52, 152, 219, 0.1);
  border-color: #3498db;
}

.sql-type-insert {
  background-color: rgba(46, 204, 113, 0.1);
  border-color: #2ecc71;
}

.sql-type-update {
  background-color: rgba(243, 156, 18, 0.1);
  border-color: #f39c12;
}

.sql-type-delete {
  background-color: rgba(231, 76, 60, 0.1);
  border-color: #e74c3c;
}

/* 风险等级边框加粗 */
.risk-critical {
  border-width: 3px;
  animation: pulse-red 2s infinite;
}

.risk-high {
  border-width: 3px;
}

@keyframes pulse-red {
  0%, 100% { box-shadow: 0 0 0 0 rgba(231, 76, 60, 0.4); }
  50% { box-shadow: 0 0 0 10px rgba(231, 76, 60, 0); }
}
</style>
```

---

## 📅 实施计划

### Phase 1: SQL性能分析器 (2天)
- Day 1: 实现核心规则和引擎
- Day 2: 集成到DAO分析器，添加N+1检测

### Phase 2: 数据血缘追踪器 (3天)
- Day 1: 实现字段解析和图构建
- Day 2: 实现来源/消费者追踪
- Day 3: 实现影响分析

### Phase 3: 可视化增强 (2天)
- Day 1: 后端数据结构增强
- Day 2: 前端组件开发和样式优化

**总计**: 7天

---

## 🎯 预期效果

### SQL性能分析
- ✅ 自动检测5种常见性能问题
- ✅ N+1查询识别准确率 > 90%
- ✅ 提供可操作的优化建议

### 数据血缘追踪
- ✅ 字段级依赖关系完整追踪
- ✅ 影响范围分析准确率 > 95%
- ✅ 支持跨表、跨模块追踪

### 可视化增强
- ✅ SQL节点一目了然
- ✅ 交互式详情查看
- ✅ 过滤和搜索功能

---

**下一步**: 开始Phase 1实施 - SQL性能分析器
