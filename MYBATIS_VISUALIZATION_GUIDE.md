# MyBatis Mapper 可视化增强指南

**版本**: v4.0  
**日期**: 2026-05-11  
**状态**: 后端已完成，待前端实现

---

## 📋 概述

本文档说明如何在调用链可视化界面中增强SQL节点的显示效果，包括颜色编码、交互式详情查看、过滤和搜索功能。

---

## 1️⃣ 后端数据结构增强

### 1.1 SQL节点数据格式

当前 `CallChainNode.to_dict()` 已包含SQL增强信息：

```json
{
  "node_id": "3|com.macro.mall.mapper.UmsMenuMapper|updateByPrimaryKeySelective",
  "package_class": "com.macro.mall.mapper.UmsMenuMapper",
  "method_signature": "updateByPrimaryKeySelective(UmsMenu)",
  "method_name": "updateByPrimaryKeySelective",
  "class_name": "UmsMenuMapper",
  "depth": 3,
  "is_leaf": true,
  
  // ✅ v4.0 新增：SQL增强信息
  "sql_enhanced": {
    "sql_type": "UPDATE",
    "tables": ["ums_menu"],
    "risk_level": "MEDIUM",
    "warning": "⚠️ UPDATE 操作会影响表: ums_menu",
    "is_dynamic_sql": true,
    "performance_score": 85,
    "performance_level": "GOOD",
    "performance_issues": [],
    "field_lineage": {
      "reads_count": 0,
      "writes_count": 2,
      "reads": [],
      "writes": [
        {"table": "ums_menu", "column": "hidden", "method": "..."},
        {"table": "ums_menu", "column": "update_time", "method": "..."}
      ]
    }
  }
}
```

### 1.2 数据字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `sql_type` | string | SQL类型: SELECT/INSERT/UPDATE/DELETE |
| `tables` | array | 涉及的表名列表 |
| `risk_level` | string | 风险等级: CRITICAL/HIGH/MEDIUM/LOW |
| `warning` | string | 警告信息 |
| `is_dynamic_sql` | boolean | 是否为动态SQL |
| `performance_score` | number | 性能评分 (0-100) |
| `performance_level` | string | 性能等级: EXCELLENT/GOOD/FAIR/POOR |
| `performance_issues` | array | 性能问题列表 |
| `field_lineage` | object | 字段血缘信息 |

---

## 2️⃣ 前端实现指南

### 2.1 SQL节点样式规范

#### 颜色编码系统

```css
/* SQL类型颜色 */
.sql-type-select {
  background-color: rgba(52, 152, 219, 0.1);
  border-color: #3498db;
  color: #2980b9;
}

.sql-type-insert {
  background-color: rgba(46, 204, 113, 0.1);
  border-color: #2ecc71;
  color: #27ae60;
}

.sql-type-update {
  background-color: rgba(243, 156, 18, 0.1);
  border-color: #f39c12;
  color: #d68910;
}

.sql-type-delete {
  background-color: rgba(231, 76, 60, 0.1);
  border-color: #e74c3c;
  color: #c0392b;
}

/* 风险等级边框 */
.risk-critical {
  border-width: 3px;
  animation: pulse-red 2s infinite;
}

.risk-high {
  border-width: 3px;
}

.risk-medium {
  border-width: 2px;
}

.risk-low {
  border-width: 1px;
}

@keyframes pulse-red {
  0%, 100% { box-shadow: 0 0 0 0 rgba(231, 76, 60, 0.4); }
  50% { box-shadow: 0 0 0 10px rgba(231, 76, 60, 0); }
}
```

#### 图标映射

```javascript
const SQL_ICONS = {
  'SELECT': '🔍',
  'INSERT': '➕',
  'UPDATE': '✏️',
  'DELETE': '🗑️'
};

const RISK_ICONS = {
  'CRITICAL': '🔴',
  'HIGH': '⚠️',
  'MEDIUM': 'ℹ️',
  'LOW': '✅'
};

const PERFORMANCE_ICONS = {
  'EXCELLENT': '⭐',
  'GOOD': '✓',
  'FAIR': '⚡',
  'POOR': '❌'
};
```

### 2.2 Vue组件示例

#### SqlNodeComponent.vue

```vue
<template>
  <div 
    class="sql-node"
    :class="[
      `sql-type-${sqlType?.toLowerCase()}`,
      `risk-${riskLevel?.toLowerCase()}`
    ]"
    @mouseenter="showTooltip"
    @mouseleave="hideTooltip"
    @click="showDetailModal"
  >
    <span class="sql-icon">{{ sqlIcon }}</span>
    <span class="sql-label">{{ sqlLabel }}</span>
    <span class="risk-badge" v-if="riskLevel && riskLevel !== 'LOW'">
      {{ riskIcon }} {{ riskLevel }}
    </span>
    <span class="perf-badge" v-if="performanceScore < 90">
      {{ performanceIcon }} {{ performanceScore }}
    </span>
  </div>
</template>

<script>
export default {
  name: 'SqlNodeComponent',
  props: {
    node: {
      type: Object,
      required: true
    }
  },
  computed: {
    sqlEnhanced() {
      return this.node.sql_enhanced || {};
    },
    sqlType() {
      return this.sqlEnhanced.sql_type;
    },
    riskLevel() {
      return this.sqlEnhanced.risk_level;
    },
    performanceScore() {
      return this.sqlEnhanced.performance_score || 100;
    },
    sqlIcon() {
      const icons = {
        'SELECT': '🔍',
        'INSERT': '➕',
        'UPDATE': '✏️',
        'DELETE': '🗑️'
      };
      return icons[this.sqlType] || '📊';
    },
    riskIcon() {
      const icons = {
        'CRITICAL': '🔴',
        'HIGH': '⚠️',
        'MEDIUM': 'ℹ️',
        'LOW': '✅'
      };
      return icons[this.riskLevel] || '';
    },
    performanceIcon() {
      const icons = {
        'EXCELLENT': '⭐',
        'GOOD': '✓',
        'FAIR': '⚡',
        'POOR': '❌'
      };
      return icons[this.sqlEnhanced.performance_level] || '';
    },
    sqlLabel() {
      const tables = this.sqlEnhanced.tables || [];
      return `${this.sqlType}: ${tables.join(', ')}`;
    }
  },
  methods: {
    showTooltip() {
      const content = this.buildTooltipContent();
      this.$emit('show-tooltip', {
        title: `${this.sqlIcon} ${this.sqlType} ${this.sqlEnhanced.tables?.join(', ')}`,
        content: content
      });
    },
    buildTooltipContent() {
      const details = this.sqlEnhanced;
      let html = `
        <div class="sql-tooltip">
          <strong>SQL类型:</strong> ${details.sql_type}<br>
          <strong>涉及表:</strong> ${details.tables?.join(', ')}<br>
          <strong>风险等级:</strong> <span class="risk-${details.risk_level?.toLowerCase()}">${details.risk_level}</span><br>
          <strong>动态SQL:</strong> ${details.is_dynamic_sql ? '是' : '否'}<br>
      `;
      
      if (details.warning) {
        html += `<strong>警告:</strong> ${details.warning}<br>`;
      }
      
      if (details.performance_score < 90) {
        html += `<strong>性能评分:</strong> ${details.performance_score}/100 (${details.performance_level})<br>`;
      }
      
      if (details.performance_issues?.length > 0) {
        html += `<strong>性能问题:</strong><ul>`;
        details.performance_issues.forEach(issue => {
          html += `<li>[${issue.severity}] ${issue.message}</li>`;
        });
        html += `</ul>`;
      }
      
      html += `</div>`;
      return html;
    },
    showDetailModal() {
      this.$emit('show-detail', {
        node: this.node,
        type: 'SQL'
      });
    },
    hideTooltip() {
      this.$emit('hide-tooltip');
    }
  }
};
</script>

<style scoped>
.sql-node {
  padding: 8px 12px;
  border-radius: 6px;
  border: 2px solid;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.sql-node:hover {
  transform: scale(1.05);
  box-shadow: 0 4px 8px rgba(0,0,0,0.2);
}

.sql-icon {
  font-size: 16px;
}

.sql-label {
  font-weight: 500;
}

.risk-badge, .perf-badge {
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  background-color: rgba(0,0,0,0.1);
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

### 2.3 SQL详情模态框

```vue
<template>
  <el-dialog
    title="SQL详细信息"
    :visible.sync="dialogVisible"
    width="700px"
  >
    <div v-if="sqlNode" class="sql-detail">
      <!-- SQL语句 -->
      <div class="detail-section">
        <h4>📋 SQL语句</h4>
        <pre class="sql-code">{{ sqlNode.sql_enhanced?.sql_content || 'N/A' }}</pre>
      </div>
      
      <!-- 元数据 -->
      <div class="detail-section">
        <h4>📊 元数据</h4>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="SQL类型">
            {{ sqlNode.sql_enhanced?.sql_type }}
          </el-descriptions-item>
          <el-descriptions-item label="涉及表">
            {{ sqlNode.sql_enhanced?.tables?.join(', ') }}
          </el-descriptions-item>
          <el-descriptions-item label="风险等级">
            <el-tag :type="getRiskTagType(sqlNode.sql_enhanced?.risk_level)">
              {{ sqlNode.sql_enhanced?.risk_level }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="动态SQL">
            {{ sqlNode.sql_enhanced?.is_dynamic_sql ? '是' : '否' }}
          </el-descriptions-item>
          <el-descriptions-item label="性能评分">
            <el-progress 
              :percentage="sqlNode.sql_enhanced?.performance_score || 100"
              :color="getPerformanceColor(sqlNode.sql_enhanced?.performance_score)"
            />
          </el-descriptions-item>
          <el-descriptions-item label="性能等级">
            {{ sqlNode.sql_enhanced?.performance_level }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
      
      <!-- 性能问题 -->
      <div class="detail-section" v-if="sqlNode.sql_enhanced?.performance_issues?.length > 0">
        <h4>⚠️ 性能问题</h4>
        <el-alert
          v-for="(issue, index) in sqlNode.sql_enhanced.performance_issues"
          :key="index"
          :title="issue.message"
          :type="getIssueType(issue.severity)"
          :description="issue.suggestion"
          show-icon
          style="margin-bottom: 10px"
        />
      </div>
      
      <!-- 字段血缘 -->
      <div class="detail-section" v-if="sqlNode.sql_enhanced?.field_lineage">
        <h4>🔗 字段血缘</h4>
        <el-tabs>
          <el-tab-pane label="读取字段" v-if="sqlNode.sql_enhanced.field_lineage.reads_count > 0">
            <el-table :data="sqlNode.sql_enhanced.field_lineage.reads" border>
              <el-table-column prop="table" label="表名" width="150" />
              <el-table-column prop="column" label="字段名" />
              <el-table-column prop="method" label="Mapper方法" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="写入字段" v-if="sqlNode.sql_enhanced.field_lineage.writes_count > 0">
            <el-table :data="sqlNode.sql_enhanced.field_lineage.writes" border>
              <el-table-column prop="table" label="表名" width="150" />
              <el-table-column prop="column" label="字段名" />
              <el-table-column prop="method" label="Mapper方法" />
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>
      
      <!-- 调用位置 -->
      <div class="detail-section">
        <h4>🔍 调用位置</h4>
        <el-timeline>
          <el-timeline-item
            timestamp="Mapper层"
            placement="top"
          >
            <el-card>
              <h4>{{ sqlNode.class_name }}.{{ sqlNode.method_name }}</h4>
              <p>{{ sqlNode.package_class }}</p>
            </el-card>
          </el-timeline-item>
          <el-timeline-item
            timestamp="Service层"
            placement="top"
            v-if="sqlNode.parent"
          >
            <el-card>
              <h4>{{ sqlNode.parent.class_name }}.{{ sqlNode.parent.method_name }}</h4>
              <p>{{ sqlNode.parent.package_class }}</p>
            </el-card>
          </el-timeline-item>
        </el-timeline>
      </div>
    </div>
    
    <span slot="footer" class="dialog-footer">
      <el-button @click="dialogVisible = false">关闭</el-button>
    </span>
  </el-dialog>
</template>

<script>
export default {
  name: 'SqlDetailModal',
  props: {
    visible: Boolean,
    sqlNode: Object
  },
  data() {
    return {
      dialogVisible: this.visible
    };
  },
  watch: {
    visible(val) {
      this.dialogVisible = val;
    },
    dialogVisible(val) {
      this.$emit('update:visible', val);
    }
  },
  methods: {
    getRiskTagType(riskLevel) {
      const types = {
        'CRITICAL': 'danger',
        'HIGH': 'warning',
        'MEDIUM': '',
        'LOW': 'success'
      };
      return types[riskLevel] || 'info';
    },
    getPerformanceColor(score) {
      if (score >= 90) return '#67c23a';
      if (score >= 70) return '#e6a23c';
      if (score >= 50) return '#f56c6c';
      return '#909399';
    },
    getIssueType(severity) {
      const types = {
        'HIGH': 'error',
        'MEDIUM': 'warning',
        'LOW': 'info'
      };
      return types[severity] || 'info';
    }
  }
};
</script>

<style scoped>
.sql-detail {
  max-height: 600px;
  overflow-y: auto;
}

.detail-section {
  margin-bottom: 20px;
}

.detail-section h4 {
  margin-bottom: 10px;
  color: #303133;
}

.sql-code {
  background-color: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  overflow-x: auto;
}
</style>
```

### 2.4 过滤器和搜索

```vue
<template>
  <div class="sql-filter-panel">
    <el-card>
      <h4>🔍 SQL过滤器</h4>
      
      <!-- SQL类型过滤 -->
      <div class="filter-group">
        <label>SQL类型:</label>
        <el-checkbox-group v-model="filters.sqlTypes">
          <el-checkbox label="SELECT">SELECT</el-checkbox>
          <el-checkbox label="INSERT">INSERT</el-checkbox>
          <el-checkbox label="UPDATE">UPDATE</el-checkbox>
          <el-checkbox label="DELETE">DELETE</el-checkbox>
        </el-checkbox-group>
      </div>
      
      <!-- 风险等级过滤 -->
      <div class="filter-group">
        <label>风险等级:</label>
        <el-checkbox-group v-model="filters.riskLevels">
          <el-checkbox label="CRITICAL">🔴 CRITICAL</el-checkbox>
          <el-checkbox label="HIGH">⚠️ HIGH</el-checkbox>
          <el-checkbox label="MEDIUM">ℹ️ MEDIUM</el-checkbox>
          <el-checkbox label="LOW">✅ LOW</el-checkbox>
        </el-checkbox-group>
      </div>
      
      <!-- 表名搜索 -->
      <div class="filter-group">
        <label>表名搜索:</label>
        <el-input
          v-model="filters.tableName"
          placeholder="输入表名..."
          clearable
          prefix-icon="el-icon-search"
        />
      </div>
      
      <!-- 性能评分过滤 -->
      <div class="filter-group">
        <label>最低性能评分:</label>
        <el-slider
          v-model="filters.minPerformanceScore"
          :max="100"
          :step="10"
          show-input
        />
      </div>
      
      <el-button type="primary" @click="applyFilters" style="width: 100%">
        应用过滤
      </el-button>
    </el-card>
  </div>
</template>

<script>
export default {
  name: 'SqlFilterPanel',
  data() {
    return {
      filters: {
        sqlTypes: ['SELECT', 'INSERT', 'UPDATE', 'DELETE'],
        riskLevels: ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'],
        tableName: '',
        minPerformanceScore: 0
      }
    };
  },
  methods: {
    applyFilters() {
      this.$emit('filter-changed', this.filters);
    }
  }
};
</script>
```

---

## 3️⃣ 实施检查清单

### 后端（已完成 ✅）

- [x] CallChainNode.to_dict() 包含 sql_enhanced 字段
- [x] DaoAnalyzer 返回 performance_score/level/issues
- [x] DaoAnalyzer 返回 field_lineage 信息
- [x] 数据结构向后兼容

### 前端（待实施 ⏳）

- [ ] 创建 SqlNodeComponent.vue 组件
- [ ] 实现颜色编码和图标显示
- [ ] 添加悬停提示功能
- [ ] 创建 SqlDetailModal.vue 模态框
- [ ] 实现SQL详情展示
- [ ] 创建 SqlFilterPanel.vue 过滤器
- [ ] 集成到调用链可视化界面
- [ ] 测试所有交互功能

---

## 4️⃣ 预期效果

### 视觉效果

```
┌──────────────────────────────────────────────┐
│ 调用链可视化                                  │
├──────────────────────────────────────────────┤
│                                              │
│ Controller.updateMenu()                      │
│   ↓                                          │
│ Service.updateMenu()                         │
│   ↓                                          │
│ 🟧✏️ UPDATE: ums_menu  ⚠️ MEDIUM  ✓85      │
│   ┌────────────────────────────────────┐    │
│   │ 🔍 悬停显示详情                     │    │
│   │ 👆 点击查看详情模态框               │    │
│   └────────────────────────────────────┘    │
│                                              │
└──────────────────────────────────────────────┘
```

### 交互体验

1. **悬停提示**: 显示SQL基本信息和警告
2. **点击展开**: 弹出详细模态框
3. **颜色区分**: 一眼识别SQL类型和风险
4. **过滤搜索**: 快速定位特定SQL节点

---

## 5️⃣ 总结

### 已完成（后端）

✅ SQL性能分析器 - 自动检测性能问题  
✅ 字段血缘追踪器 - 追踪字段依赖关系  
✅ 数据结构增强 - 完整的SQL节点信息  

### 待实施（前端）

⏳ SQL节点组件 - 颜色编码和图标  
⏳ 详情模态框 - 交互式详情查看  
⏳ 过滤器面板 - 过滤和搜索功能  

### 下一步

1. 前端团队根据本文档实现UI组件
2. 联调测试确保数据显示正确
3. 用户反馈收集和优化

---

**文档版本**: v1.0  
**创建日期**: 2026-05-11  
**作者**: Lingma AI Assistant  
**状态**: 后端完成，前端待实施
