# Streamlit 前端 SQL 增强功能使用指南

**版本**: v4.0  
**更新日期**: 2026-05-11  
**状态**: ✅ 已完成并测试

---

## 📋 概述

Streamlit 前端已完全支持 MyBatis Mapper v4.0 的所有增强功能，包括：

1. **SQL 性能分析展示** - 可视化显示性能评分和问题
2. **字段血缘追踪** - 展示字段级依赖关系
3. **SQL 分析汇总视图** - 集中查看所有 DAO 方法

---

## 🎯 核心功能

### 1️⃣ 调用链中的 SQL 增强信息

在**向上分析**和**向下分析**标签页中，当展开包含 DAO 方法的调用链时，会自动显示 SQL 增强信息。

#### 显示内容

```
🗄️ SQL 增强信息 (v4.0)
├── 基本信息
│   ├── SQL类型: UPDATE (橙色高亮)
│   ├── 表名: ums_menu
│   └── 实体类: UmsMenu
│
├── 📝 查看完整SQL语句 (可折叠)
│   └── UPDATE ums_menu SET hidden = ? WHERE id = ?
│
├── ⚡ 性能分析
│   ├── 性能评分徽章: 80分 (GOOD)
│   └── 性能问题列表:
│       ├── 🔴 [HIGH] FULL_TABLE_SCAN
│       │   ├── 💬 SELECT语句缺少WHERE条件
│       │   └── 💡 添加WHERE条件或LIMIT限制
│       └── 🟡 [MEDIUM] SELECT_STAR
│           ├── 💬 使用SELECT *可能返回不必要的列
│           └── 💡 明确指定需要的列名
│
└── 🔗 字段血缘追踪
    ├── 📊 共追踪 3 个字段
    ├── 📥 数据来源 (2个字段)
    │   ├── ums_menu.name
    │   └── ums_menu.sort
    ├── 📤 数据消费者 (1个字段)
    │   └── ums_menu.id
    └── 变更影响评估: LOW
        └── 建议:
            - 检查下游系统的字段使用情况
            - 确保API兼容性
```

#### 颜色编码

| 元素 | 颜色 | 说明 |
|------|------|------|
| **SQL类型** | | |
| SELECT | 🔵 蓝色 | 查询操作 |
| INSERT | 🟢 绿色 | 插入操作 |
| UPDATE | 🟠 橙色 | 更新操作 |
| DELETE | 🔴 红色 | 删除操作 |
| **性能等级** | | |
| EXCELLENT (90-100) | 🟢 绿色 | 优秀 |
| GOOD (70-89) | 🔵 蓝色 | 良好 |
| FAIR (50-69) | 🟠 橙色 | 一般 |
| POOR (<50) | 🔴 红色 | 较差 |
| **问题严重程度** | | |
| HIGH | 🔴 红色圆圈 | 高风险 |
| MEDIUM | 🟡 黄色圆圈 | 中等风险 |
| LOW | 🟢 绿色圆圈 | 低风险 |

---

### 2️⃣ SQL 分析汇总视图

新增的 **🗄️ SQL分析** 标签页提供所有 DAO 方法的集中视图。

#### 功能特性

##### A. 统计仪表板

显示4个关键指标：

1. **SQL 类型分布**
   ```
   SQL 类型分布: 3 种
     • SELECT: 15
     • UPDATE: 8
     • INSERT: 3
   ```

2. **性能等级分布**
   ```
   性能等级分布: 3 级
     • EXCELLENT: 10
     • GOOD: 12
     • FAIR: 4
   ```

3. **涉及表数量**
   ```
   涉及表数量: 8
     • ums_admin
     • ums_menu
     • oms_order
     • ...
   ```

4. **变更类型分布**
   ```
   变更类型分布: 2 种
     • MODIFIED: 20
     • ADDED: 6
   ```

##### B. 多维度过滤器

提供3个过滤维度：

1. **SQL 类型** (多选)
   - ☑️ SELECT
   - ☑️ INSERT
   - ☑️ UPDATE
   - ☑️ DELETE

2. **性能等级** (多选)
   - ☑️ EXCELLENT
   - ☑️ GOOD
   - ☑️ FAIR
   - ☑️ POOR

3. **最低性能评分** (滑块)
   - 范围: 0-100
   - 默认: 0 (显示全部)

##### C. 方法列表

每个 DAO 方法以可折叠面板形式展示：

```
1. [MODIFIED] UmsMenuServiceImpl.updateHidden() - 
   UPDATE on `ums_menu` - 80分 (GOOD)
   
   点击展开后显示完整的 SQL 增强信息
```

标题中包含：
- 变更类型: `[MODIFIED]`
- 方法签名: `UmsMenuServiceImpl.updateHidden()`
- SQL 类型: `UPDATE` (彩色)
- 表名: `` `ums_menu` ``
- 性能评分: `80分 (GOOD)` (彩色)

---

## 🚀 使用方法

### 步骤 1: 启动 Streamlit 应用

```bash
cd c:\Users\carpe\VisualStudioProject\TestPlatform\jcci
streamlit run src/jcci/workflow/streamlit_app.py
```

### 步骤 2: 访问正确的 URL

必须通过 URL 参数指定基线：

```
http://localhost:8501/?baseline=mall_20260508_01
```

### 步骤 3: 选择目标版本

在侧边栏中选择：
1. **基线版本**: `mall_20260508_01`
2. **目标版本**: `20260508_02`

系统会自动加载对应的数据库和调用链数据。

### 步骤 4: 查看 SQL 增强信息

#### 方式 A: 在调用链中查看

1. 切换到 **⬇️ 向下分析** 标签页
2. 展开任意包含 Mapper/DAO 方法的调用链
3. 滚动到底部，查看 **🗄️ SQL 增强信息** 区域

#### 方式 B: 在 SQL 分析视图中查看

1. 切换到 **🗄️ SQL分析** 标签页
2. 查看顶部的统计仪表板
3. 使用过滤器筛选感兴趣的方法
4. 点击展开任意方法查看详细 SQL 信息

---

## 💡 最佳实践

### 1. 快速定位性能问题

**场景**: 找出所有性能较差的 SQL

**操作**:
1. 进入 **🗄️ SQL分析** 标签页
2. 在"性能等级"过滤器中只选择 `POOR` 和 `FAIR`
3. 或在"最低性能评分"滑块中设置为 `50`
4. 查看过滤后的方法列表，优先优化这些问题

### 2. 分析特定表的变更影响

**场景**: 了解 `ums_menu` 表的所有操作

**操作**:
1. 进入 **🗄️ SQL分析** 标签页
2. 在"涉及表数量"卡片中确认 `ums_menu` 存在
3. 目前暂不支持按表名过滤（未来版本会添加）
4. 可以手动浏览列表，查找包含 `ums_menu` 的方法

### 3. 审查高风险操作

**场景**: 找出所有 DELETE 操作

**操作**:
1. 进入 **🗄️ SQL分析** 标签页
2. 在"SQL 类型"过滤器中只选择 `DELETE`
3. 查看所有删除操作，确认是否有缺少 WHERE 条件的风险

### 4. 追踪字段变更影响

**场景**: 修改了 `ums_menu.name` 字段，想知道影响范围

**操作**:
1. 找到操作 `ums_menu` 表的方法
2. 展开 **🔗 字段血缘追踪** 部分
3. 查看 **📤 数据消费者** 列表，了解哪些地方读取了这个字段
4. 查看 **变更影响评估** 的建议

---

## 🔧 故障排查

### 问题 1: 未检测到 MyBatis Mapper/DAO 方法

**现象**: SQL 分析视图显示 "未检测到 MyBatis Mapper/DAO 方法"

**原因**:
1. 项目不包含 MyBatis Mapper XML 文件
2. 运行 workflow 时未提供 `source_dir` 参数
3. XML 文件路径不符合扫描规则

**解决方案**:

```python
# ✅ 正确：提供 source_dir
result = analyze_two_commit_incremental(
    baseline_commit='mall_20260508_01',
    current_commit='20260508_02',
    source_dir='/path/to/mall'  # ← 必须提供
)

# ❌ 错误：缺少 source_dir
result = analyze_two_commit_incremental(
    baseline_commit='mall_20260508_01',
    current_commit='20260508_02'
    # 没有 source_dir，无法扫描 XML
)
```

**XML 文件扫描规则**:
- MBG生成的Mapper: `**/mall-mbg/**/*Mapper.xml`
- 自定义DAO: `**/dao/**/*.xml`
- 通用匹配: `**/*Mapper.xml`

### 问题 2: SQL 增强信息不显示

**现象**: 调用链中有 Mapper 方法，但没有显示 SQL 增强信息

**原因**:
1. `dao_info` 字段为 `null`
2. 数据结构不正确

**检查方法**:

打开浏览器开发者工具，查看 JSON 数据结构：

```javascript
// 在浏览器控制台执行
fetch('/api/chains')  // 或查看加载的 JSON 文件
  .then(r => r.json())
  .then(data => {
    console.log(data.dependency_chains[0].method_info.dao_info);
  });
```

**期望结构**:

```json
{
  "dao_info": {
    "is_dao": true,
    "sql_type": "UPDATE",
    "table_name": "ums_menu",
    "entity_name": "UmsMenu",
    "sql_statement": "UPDATE ums_menu SET ...",
    "performance_score": 80,
    "performance_level": "GOOD",
    "performance_issues": [...],
    "field_lineage": {...}
  }
}
```

### 问题 3: 性能评分显示为 0

**现象**: 所有方法的性能评分都是 0 分

**原因**:
1. 后端未初始化 `SqlPerformanceAnalyzer`
2. `dao_analyzer.py` 中未调用性能分析

**解决方案**:

检查后端代码是否正确集成：

```python
# dao_analyzer.py 中应该有:
from .sql_performance_analyzer import SqlPerformanceAnalyzer

class DaoAnalyzer:
    def __init__(self, mapper_index):
        self.mapper_index = mapper_index
        self.performance_analyzer = SqlPerformanceAnalyzer()  # ← 必须有这行
```

---

## 📊 数据结构说明

### CallChainNode.dao_info 字段

```typescript
interface DaoInfo {
  is_dao: boolean;                    // 是否为 DAO 方法
  dao_type: string;                   // MYBATIS / JPA / JDBC
  entity_name?: string;               // 实体类名
  entity_class?: string;              // 实体全限定名
  table_name?: string;                // 表名
  sql_type?: string;                  // SELECT / INSERT / UPDATE / DELETE
  sql_statement?: string;             // 完整 SQL 语句
  
  // v4.0 新增
  performance_score?: number;         // 性能评分 (0-100)
  performance_level?: string;         // EXCELLENT / GOOD / FAIR / POOR
  performance_issues?: PerformanceIssue[];  // 性能问题列表
  field_lineage?: FieldLineageReport; // 字段血缘报告
}

interface PerformanceIssue {
  rule: string;                       // 规则名称
  severity: string;                   // HIGH / MEDIUM / LOW
  message: string;                    // 问题描述
  suggestion: string;                 // 优化建议
  affected_tables?: string[];         // 影响的表
}

interface FieldLineageReport {
  sources: DataSource[];              // 数据来源（写入的字段）
  consumers: DataConsumer[];          // 数据消费者（读取的字段）
  statistics: {
    total_fields_tracked: number;     // 追踪的字段总数
  };
  impact_analysis?: {
    risk_level: string;               // CRITICAL / HIGH / MEDIUM / LOW
    affected_fields: number;          // 影响的字段数
    consumers_count: number;          // 消费者数量
    recommendations: string[];        // 建议列表
  };
}
```

---

## 🎨 UI 组件说明

### 1. 性能评分徽章

使用 HTML + CSS 实现的自定义徽章：

```html
<div style='text-align:center;padding:10px;border-radius:5px;
            background-color:{level_color}20;border:2px solid {level_color}'>
  <div style='font-size:24px;font-weight:bold;color:{level_color}'>80</div>
  <div style='font-size:12px;color:{level_color}'>GOOD</div>
</div>
```

**特点**:
- 背景色透明度 20% (`{color}20`)
- 边框宽度 2px
- 居中对齐
- 大号数字 + 小号等级文字

### 2. 可折叠面板 (Expander)

使用 Streamlit 的 `st.expander()` 组件：

```python
with st.expander("标题", expanded=False):
    # 详细内容
    st.markdown("...")
```

**优点**:
- 节省空间
- 按需展开
- 支持 Markdown 渲染

### 3. 多列布局

使用 `st.columns()` 实现响应式布局：

```python
col1, col2, col3 = st.columns(3)

with col1:
    st.metric("指标1", "值1")

with col2:
    st.metric("指标2", "值2")

with col3:
    st.metric("指标3", "值3")
```

**特点**:
- 自动适应屏幕宽度
- 移动端自动换行
- 支持不等宽列 (`st.columns([1, 3])`)

---

## 🔄 与后端的集成

### 数据流

```
后端 (Python)                          前端 (Streamlit)
─────────────                          ─────────────

1. Workflow 运行
   ├─ 扫描 XML 文件
   ├─ 构建 MapperIndex
   └─ 创建 DaoAnalyzer

2. 调用链分析
   ├─ DownwardsCallChainBuilder
   ├─ 识别 DAO 方法
   └─ 生成 dao_info

3. 保存 JSON
   └─ downwards_call_chains.json
      └─ method_info.dao_info {
           sql_type, tables,
           performance_score,
           field_lineage, ...
         }
                                          4. 加载 JSON
                                             └─ load_json_file()

                                          5. 渲染调用链
                                             └─ render_downwards_analysis()
                                                ├─ 检测 dao_info
                                                └─ render_sql_enhanced_info()

                                          6. 用户交互
                                             ├─ 展开面板
                                             ├─ 查看 SQL
                                             └─ 过滤方法
```

### 关键集成点

#### 1. 调用链节点渲染

```python
# streamlit_app.py: render_downwards_analysis()

for idx, chain_data in enumerate(dependency_chains, 1):
    method_info = chain_data.get('method_info', {})
    
    # ✅ 检测并渲染 SQL 增强信息
    dao_info = method_info.get('dao_info')
    if dao_info and dao_info.get('is_dao'):
        render_sql_enhanced_info(dao_info)
```

#### 2. SQL 分析汇总

```python
# streamlit_app.py: render_sql_analysis_view()

# 提取所有 DAO 方法
dao_methods = []
for chain_data in dependency_chains:
    method_info = chain_data.get('method_info', {})
    dao_info = method_info.get('dao_info')
    
    if dao_info and dao_info.get('is_dao'):
        dao_methods.append({
            'method_info': method_info,
            'dao_info': dao_info
        })

# 统计、过滤、渲染
# ...
```

---

## 📈 性能优化建议

### 1. 减少 DOM 节点数量

**问题**: 当有数百个 DAO 方法时，页面可能变慢

**解决方案**:
- 默认折叠所有面板 (`expanded=False`)
- 使用过滤器减少显示数量
- 考虑分页（未来版本）

### 2. 缓存渲染结果

Streamlit 自动缓存函数结果，但可以进一步优化：

```python
@st.cache_data(ttl=3600)
def extract_dao_methods(downwards_data: Dict) -> List[Dict]:
    """提取并缓存 DAO 方法列表"""
    # ...
```

### 3. 懒加载 SQL 语句

**当前**: 所有 SQL 语句都加载到内存

**优化**: 只在用户点击"查看完整SQL"时才渲染

```python
if st.button("查看SQL"):
    st.code(sql_statement, language='sql')
```

---

## 🚧 未来改进方向

### 短期（1-2周）

1. **按表名过滤**
   - 添加表名多选框
   - 快速定位特定表的操作

2. **导出功能**
   - 导出为 CSV/Excel
   - 导出性能报告

3. **搜索功能**
   - 按方法名搜索
   - 按表名搜索
   - 按 SQL 关键字搜索

### 中期（1-2月）

1. **图表可视化**
   - 饼图: SQL 类型分布
   - 柱状图: 性能等级分布
   - 折线图: 性能趋势（历史对比）

2. **交互式血缘图**
   - 使用 Graphviz 或 ECharts
   - 展示字段依赖关系图
   - 支持缩放和拖拽

3. **批量操作**
   - 批量标记已审查
   - 批量导出报告
   - 批量添加注释

### 长期（3-6月）

1. **实时分析**
   - WebSocket 连接后端
   - 实时显示分析进度
   - 动态更新结果

2. **协作功能**
   - 多人评论和标注
   - 审查状态跟踪
   - 问题分配和跟进

3. **AI 辅助**
   - 自动生成优化建议
   - 智能代码重构推荐
   - 自然语言查询

---

## 📞 技术支持

如有问题或建议，请通过以下方式联系：

- **GitHub Issues**: [jcci/issues](https://github.com/your-repo/jcci/issues)
- **文档反馈**: 直接在对应 Markdown 文件中提 PR
- **前端问题**: 查看浏览器控制台的错误信息

---

## 📝 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v4.0 | 2026-05-11 | 初始版本，完整支持 SQL 增强功能 |

---

**文档维护者**: JCCI Team  
**最后更新**: 2026-05-11
