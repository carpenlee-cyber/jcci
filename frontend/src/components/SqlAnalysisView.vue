<template>
  <div class="sql-analysis-view">
    <el-card v-loading="loading">
      <template #header>
        <div class="card-header">
          <span>🗄️ SQL 分析视图</span>
        </div>
      </template>

      <!-- 统计信息 -->
      <el-row :gutter="20" v-if="summary">
        <el-col :span="6">
          <el-statistic title="DAO 方法数" :value="summary.total_dao_methods" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="涉及表数量" :value="summary.total_tables" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="SQL 类型数" :value="Object.keys(summary.sql_type_distribution).length" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="性能等级数" :value="Object.keys(summary.performance_level_distribution).length" />
        </el-col>
      </el-row>

      <el-divider />

      <!-- 过滤器 -->
      <el-form inline>
        <el-form-item label="SQL 类型">
          <el-select v-model="selectedSqlTypes" multiple placeholder="选择 SQL 类型" style="width: 200px" @change="applyFilter">
            <el-option v-for="type in sqlTypes" :key="type" :label="type" :value="type" />
          </el-select>
        </el-form-item>
        <el-form-item label="性能等级">
          <el-select v-model="selectedPerfLevels" multiple placeholder="选择性能等级" style="width: 200px" @change="applyFilter">
            <el-option label="EXCELLENT" value="EXCELLENT" />
            <el-option label="GOOD" value="GOOD" />
            <el-option label="FAIR" value="FAIR" />
            <el-option label="POOR" value="POOR" />
          </el-select>
        </el-form-item>
        <el-form-item label="最低评分">
          <el-slider v-model="minScore" :max="100" style="width: 200px" @change="applyFilter" />
        </el-form-item>
      </el-form>

      <el-alert :title="`显示 ${filteredMethods.length} / ${daoMethods.length} 个方法`" type="info" :closable="false" style="margin-bottom: 15px" />

      <!-- DAO 方法列表 -->
      <el-table :data="filteredMethods" stripe style="width: 100%">
        <el-table-column prop="method_info.class_name" label="类名" width="200" />
        <el-table-column prop="method_info.method_name" label="方法名" width="200" />
        <el-table-column label="SQL 类型" width="120">
          <template #default="{ row }">
            <el-tag :type="getSqlTypeColor(row.dao_info.sql_type)">{{ row.dao_info.sql_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="dao_info.table_name" label="表名" width="150" />
        <el-table-column label="性能评分" width="150">
          <template #default="{ row }">
            <el-progress :percentage="row.dao_info.performance_score || 0" :color="getPerformanceColor(row.dao_info.performance_level)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" fixed="right" width="120">
          <template #default="{ row }">
            <el-button size="small" @click="viewDetails(row)">查看详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="filteredMethods.length === 0" description="未找到匹配的 DAO 方法" />
    </el-card>

    <!-- 详情对话框 -->
    <el-dialog v-model="dialogVisible" title="SQL 详细信息" width="70%">
      <div v-if="selectedMethod" class="detail-content">
        <h4>基本信息</h4>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="类名">{{ selectedMethod.method_info.class_name }}</el-descriptions-item>
          <el-descriptions-item label="方法名">{{ selectedMethod.method_info.method_name }}</el-descriptions-item>
          <el-descriptions-item label="SQL 类型">{{ selectedMethod.dao_info.sql_type }}</el-descriptions-item>
          <el-descriptions-item label="表名">{{ selectedMethod.dao_info.table_name }}</el-descriptions-item>
          <el-descriptions-item label="实体类">{{ selectedMethod.dao_info.entity_name }}</el-descriptions-item>
          <el-descriptions-item label="性能评分">{{ selectedMethod.dao_info.performance_score }}</el-descriptions-item>
        </el-descriptions>

        <h4 style="margin-top: 20px">SQL 语句</h4>
        <el-input type="textarea" :rows="8" :value="selectedMethod.dao_info.sql_statement || '无'" readonly />

        <h4 style="margin-top: 20px">性能问题</h4>
        <el-alert v-if="selectedMethod.dao_info.performance_issues?.length > 0" :title="`发现 ${selectedMethod.dao_info.performance_issues.length} 个性能问题`" type="warning" :closable="false">
          <div v-for="(issue, idx) in selectedMethod.dao_info.performance_issues" :key="idx" style="margin-top: 10px">
            <strong>[{{ issue.severity }}]</strong> {{ issue.rule }}<br/>
            💬 {{ issue.message }}<br/>
            💡 {{ issue.suggestion }}
          </div>
        </el-alert>
        <el-alert v-else title="✅ 未检测到性能问题" type="success" :closable="false" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import { useRoute } from 'vue-router'

const route = useRoute()
const loading = ref(false)
const dialogVisible = ref(false)
const selectedMethod = ref<any>(null)

const summary = ref<any>(null)
const daoMethods = ref<any[]>([])
const filteredMethods = ref<any[]>([])

const selectedSqlTypes = ref<string[]>([])
const selectedPerfLevels = ref<string[]>([])
const minScore = ref(0)

const sqlTypes = computed(() => {
  if (!summary.value) return []
  return Object.keys(summary.value.sql_type_distribution || {})
})

const apiClient = axios.create({
  baseURL: 'http://127.0.0.1:8000/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' }
})

const loadSqlSummary = async () => {
  const baseline = route.query.baseline as string || 'test_baseline'
  const version = route.query.version as string || 'test_version'

  loading.value = true
  try {
    const response = await apiClient.get(`/analysis/${baseline}/${version}/sql-summary`)
    summary.value = response.data.summary
    await loadDaoMethods(baseline, version)
  } catch (error) {
    console.error('加载 SQL 汇总失败:', error)
    ElMessage.error('加载 SQL 数据失败')
  } finally {
    loading.value = false
  }
}

const loadDaoMethods = async (baseline: string, version: string) => {
  try {
    const response = await apiClient.get(`/analysis/${baseline}/${version}/downwards`)
    const data = response.data
    const chains = data.dependency_chains || data.call_chains || []
    daoMethods.value = chains.filter((chain: any) => {
      return chain.method_info?.dao_info?.is_dao
    })
    applyFilter()
  } catch (error) {
    console.error('加载 DAO 方法失败:', error)
  }
}

const applyFilter = () => {
  filteredMethods.value = daoMethods.value.filter((method: any) => {
    const daoInfo = method.dao_info
    const sqlType = daoInfo.sql_type
    const perfLevel = daoInfo.performance_level
    const perfScore = daoInfo.performance_score || 0
    if (selectedSqlTypes.value.length > 0 && !selectedSqlTypes.value.includes(sqlType)) return false
    if (selectedPerfLevels.value.length > 0 && !selectedPerfLevels.value.includes(perfLevel)) return false
    if (perfScore < minScore.value) return false
    return true
  })
}

const viewDetails = (method: any) => {
  selectedMethod.value = method
  dialogVisible.value = true
}

const getSqlTypeColor = (type: string) => {
  const map: Record<string, any> = { SELECT: 'primary', INSERT: 'success', UPDATE: 'warning', DELETE: 'danger' }
  return map[type] || 'info'
}

const getPerformanceColor = (level: string) => {
  const map: Record<string, string> = { EXCELLENT: '#67c23a', GOOD: '#409eff', FAIR: '#e6a23c', POOR: '#f56c6c' }
  return map[level] || '#909399'
}

onMounted(() => {
  loadSqlSummary()
})
</script>

<style scoped>
.sql-analysis-view { padding: 20px; }
.card-header { font-weight: bold; font-size: 16px; }
.detail-content h4 { margin-top: 20px; margin-bottom: 10px; color: #409EFF; }
</style>
