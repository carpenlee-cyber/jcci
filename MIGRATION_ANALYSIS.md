# JCCI 平台功能迁移分析报告

## 📊 Streamlit 版本核心功能清单

### 1. 任务管理模块 ✅ 已迁移
- [x] 任务提交页面（表单输入）
- [x] 任务列表展示
- [x] 任务状态监控（pending/running/completed/failed）
- [x] 任务取消功能
- [x] 参数缓存（localStorage）
- [x] 自动跳转（提交后跳转到任务列表）
- [x] 队列位置显示
- [x] 预估等待时间

**迁移状态**: ✅ 100% 完成
**文件**: `frontend/src/views/TaskSubmit.vue`, `frontend/src/views/TaskList.vue`

---

### 2. 调用链分析展示 ⚠️ 部分迁移
- [x] 向上调用链树形图（基础版）
- [x] 向下调用链树形图（基础版）
- [ ] **调用链数据加载** ❌ 缺失
- [ ] **基线版本选择** ❌ 缺失
- [ ] **版本子目录选择** ❌ 缺失
- [ ] **数据库隔离机制** ❌ 缺失

**迁移状态**: ⚠️ 40% 完成
**问题**: 
- 当前使用模拟数据，未集成实际的数据加载逻辑
- 缺少基线和版本选择的侧边栏
- 未实现多基线数据库隔离

**关键代码位置**: 
- Streamlit: `streamlit_app.py` L1213-1298 (`render_sidebar`)
- Streamlit: `streamlit_app.py` L605-643 (`get_session_db_path`)

---

### 3. LLM 智能分析 ❌ 未迁移
- [ ] 单方法 AI 分析
- [ ] 调用链 AI 分析
- [ ] LLM 缓存机制
- [ ] 异步分析线程
- [ ] 强制全新分析选项
- [ ] 分析进度实时显示

**迁移状态**: ❌ 0% 完成
**影响**: 这是 Streamlit 版本的核心亮点功能

**关键代码位置**:
- Streamlit: `streamlit_app.py` L948-1078 (`analyze_single_method`)
- Streamlit: `streamlit_app.py` L1081-1209 (`analyze_call_chain`)
- Streamlit: `streamlit_app.py` L786-822 (`start_async_analysis`)
- Streamlit: `streamlit_app.py` L833-906 (LLM 缓存函数)

---

### 4. SQL 增强分析 ❌ 未迁移
- [ ] DAO 方法识别
- [ ] SQL 语句展示
- [ ] 性能评分系统
- [ ] 字段血缘追踪
- [ ] SQL 分析视图（独立 Tab）
- [ ] SQL 类型过滤
- [ ] 性能等级过滤

**迁移状态**: ❌ 0% 完成
**影响**: v4.0 重要特性，提供数据库层面的深度分析

**关键代码位置**:
- Streamlit: `streamlit_app.py` L1452-1592 (`render_sql_enhanced_info`)
- Streamlit: `streamlit_app.py` L1744-1919 (`render_sql_analysis_view`)

---

### 5. 文本视图 ⚠️ 基础迁移
- [x] 文本查看器组件
- [ ] 等宽字体渲染优化
- [ ] 文本数据实时加载

**迁移状态**: ⚠️ 50% 完成
**文件**: `frontend/src/components/TextViewer.vue`

---

### 6. 会话管理 ❌ 未迁移
- [ ] 用户会话 ID 生成
- [ ] 会话专用数据库路径
- [ ] URL 参数传递（baseline）
- [ ] 页面导航辅助函数

**迁移状态**: ❌ 0% 完成
**影响**: 多用户并发访问时的数据隔离

**关键代码位置**:
- Streamlit: `streamlit_app.py` L596-602 (`get_user_session_id`)
- Streamlit: `streamlit_app.py` L605-643 (`get_session_db_path`)
- Streamlit: `streamlit_app.py` L55-94 (导航函数)

---

### 7. 数据加载与缓存 ⚠️ 部分迁移
- [x] API 调用封装
- [ ] JSON 文件加载（带缓存）
- [ ] 文本文件加载（无缓存）
- [ ] 数据库查询（带缓存）
- [ ] 方法信息从数据库补充

**迁移状态**: ⚠️ 30% 完成
**问题**: 前端仅实现了 API 调用，未实现本地文件加载和数据库查询

**关键代码位置**:
- Streamlit: `streamlit_app.py` L656-694 (数据加载函数)
- Streamlit: `streamlit_app.py` L697-769 (`get_method_info_from_db`)

---

### 8. UI 交互增强 ❌ 未迁移
- [ ] 自动刷新（meta refresh）
- [ ] 手动刷新按钮
- [ ] 任务统计指标卡片
- [ ] 队列状态提示
- [ ] 错误消息详细展示

**迁移状态**: ❌ 0% 完成

---

## 🎯 迁移优先级建议

### P0 - 核心功能（必须完成）
1. **调用链数据加载** - 从文件系统加载 JSON 数据
2. **基线版本选择** - 侧边栏选择基线和版本
3. **数据库隔离** - 根据基线选择对应数据库

### P1 - 重要功能（强烈建议）
4. **LLM 智能分析** - 后端 API + 前端异步调用
5. **SQL 增强分析** - DAO 方法识别和展示
6. **会话管理** - 多用户数据隔离

### P2 - 体验优化（可选）
7. **自动刷新机制** - 实时进度更新
8. **文本视图优化** - 等宽字体渲染
9. **统计卡片** - 任务和数据统计

---

## 📋 详细迁移计划

### 阶段 1: 数据加载与基线选择（P0）

#### 1.1 后端 API 扩展
**文件**: `backend/app/api/analysis.py` (新建)

```python
# 新增端点
GET /api/analysis/baselines          # 获取所有可用基线
GET /api/analysis/{baseline}/versions # 获取基线下的版本
GET /api/analysis/{baseline}/{version}/upwards   # 获取向上调用链
GET /api/analysis/{baseline}/{version}/downwards # 获取向下调用链
GET /api/analysis/{baseline}/{version}/text      # 获取文本视图
```

**实现要点**:
- 扫描 `RESULT_DIR` 目录
- 读取 JSON 文件
- 支持基线和版本两级选择

#### 1.2 前端基线选择组件
**文件**: `frontend/src/components/BaselineSelector.vue` (新建)

```vue
<template>
  <el-cascader
    v-model="selectedBaseline"
    :options="baselineOptions"
    @change="handleBaselineChange"
  />
</template>
```

#### 1.3 更新 AnalysisResult 页面
**文件**: `frontend/src/views/AnalysisResult.vue`

- 添加基线选择器到侧边栏
- 替换模拟数据为真实 API 调用
- 实现数据加载 loading 状态

---

### 阶段 2: LLM 智能分析（P1）

#### 2.1 后端 LLM 服务
**文件**: `backend/app/services/llm_service.py` (新建)

```python
class LLMService:
    def analyze_method(self, method_info, db_info, direction)
    def analyze_chain(self, chain_data, direction)
    def get_cached_result(self, ...)
    def save_to_cache(self, ...)
```

**依赖**:
- `requests` 库调用 LLM API
- SQLite 缓存表操作

#### 2.2 后端 API 端点
**文件**: `backend/app/api/analysis.py`

```python
POST /api/analysis/{task_id}/method   # 分析方法
POST /api/analysis/{task_id}/chain    # 分析调用链
GET  /api/analysis/{task_id}/status   # 查询分析状态
```

#### 2.3 前端异步分析组件
**文件**: `frontend/src/components/LLMAnalyzer.vue` (新建)

```vue
<template>
  <el-button @click="startAnalysis" :loading="analyzing">
    🤖 AI 分析
  </el-button>
  
  <div v-if="result" class="analysis-result">
    <markdown-renderer :content="result" />
  </div>
</template>
```

**技术要点**:
- 使用 WebSocket 或轮询获取实时进度
- Markdown 渲染（使用 `marked` 或 `markdown-it`）
- 缓存标识显示

---

### 阶段 3: SQL 增强分析（P1）

#### 3.1 后端 SQL 分析服务
**文件**: `backend/app/services/sql_analyzer.py` (新建)

```python
class SQLAnalyzer:
    def extract_dao_methods(self, call_chains)
    def analyze_performance(self, dao_info)
    def trace_field_lineage(self, sql_statement)
```

#### 3.2 前端 SQL 分析视图
**文件**: `frontend/src/components/SqlAnalysisView.vue` (新建)

```vue
<template>
  <el-table :data="daoMethods">
    <el-table-column prop="sql_type" label="SQL类型" />
    <el-table-column prop="table_name" label="表名" />
    <el-table-column prop="performance_score" label="性能评分" />
  </el-table>
  
  <el-expander v-for="method in daoMethods">
    <render-sql-enhanced-info :dao-info="method.dao_info" />
  </el-expander>
</template>
```

---

### 阶段 4: 会话管理与优化（P2）

#### 4.1 前端会话管理
**文件**: `frontend/src/stores/session.ts` (新建)

```typescript
export const useSessionStore = defineStore('session', () => {
  const sessionId = ref(generateUUID())
  const currentBaseline = ref('')
  
  function setBaseline(baseline: string) {
    currentBaseline.value = baseline
    // 更新 URL 参数
  }
})
```

#### 4.2 URL 参数同步
**文件**: `frontend/src/router/index.ts`

```typescript
// 监听路由变化，同步 baseline 参数
router.afterEach((to) => {
  if (to.query.baseline) {
    sessionStore.setBaseline(to.query.baseline as string)
  }
})
```

---

## 🔍 当前缺失的关键功能对比表

| 功能模块 | Streamlit | Vue 3 | 状态 | 优先级 |
|---------|-----------|-------|------|--------|
| 任务提交 | ✅ | ✅ | ✅ 完成 | - |
| 任务列表 | ✅ | ✅ | ✅ 完成 | - |
| 基线选择 | ✅ | ❌ | ❌ 缺失 | P0 |
| 版本选择 | ✅ | ❌ | ❌ 缺失 | P0 |
| 数据加载 | ✅ | ❌ | ❌ 缺失 | P0 |
| 数据库隔离 | ✅ | ❌ | ❌ 缺失 | P0 |
| 向上调用链 | ✅ | ⚠️ | ⚠️ 模拟数据 | P0 |
| 向下调用链 | ✅ | ⚠️ | ⚠️ 模拟数据 | P0 |
| LLM 方法分析 | ✅ | ❌ | ❌ 缺失 | P1 |
| LLM 链路分析 | ✅ | ❌ | ❌ 缺失 | P1 |
| LLM 缓存 | ✅ | ❌ | ❌ 缺失 | P1 |
| SQL 分析视图 | ✅ | ❌ | ❌ 缺失 | P1 |
| DAO 方法识别 | ✅ | ❌ | ❌ 缺失 | P1 |
| 性能评分 | ✅ | ❌ | ❌ 缺失 | P1 |
| 字段血缘 | ✅ | ❌ | ❌ 缺失 | P1 |
| 文本视图 | ✅ | ⚠️ | ⚠️ 基础版 | P2 |
| 自动刷新 | ✅ | ⚠️ | ⚠️ 部分实现 | P2 |
| 会话管理 | ✅ | ❌ | ❌ 缺失 | P2 |

**完成率**: 约 30% (6/20 核心功能)

---

## 💡 实施建议

### 短期目标（1-2周）
1. 实现基线和版本选择功能
2. 集成真实数据加载
3. 完成调用链可视化

### 中期目标（3-4周）
4. 实现 LLM 智能分析
5. 添加 SQL 增强分析
6. 完善会话管理

### 长期目标（5-6周）
7. 性能优化和用户体验提升
8. 文档和完善测试
9. Docker 部署验证

---

## 📝 下一步行动

**立即执行**:
1. 创建 `backend/app/api/analysis.py` - 数据加载 API
2. 创建 `frontend/src/components/BaselineSelector.vue` - 基线选择器
3. 更新 `AnalysisResult.vue` - 集成真实数据

**预计工作量**: 
- P0 功能: 3-5 天
- P1 功能: 7-10 天
- P2 功能: 3-5 天
- **总计**: 2-3 周

---

**结论**: 当前迁移完成了基础架构和任务管理，但核心的分析展示功能尚未完整迁移。建议优先完成 P0 级别的数据加载和基线选择功能，使平台能够真正展示分析结果。
