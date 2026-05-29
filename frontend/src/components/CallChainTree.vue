<template>
  <div class="call-chain-tree">
    <h3 v-if="title">{{ title }}</h3>
    
    <!-- AI 批量分析按钮（逐方法触发 analyze_method） -->
    <div v-if="showBulkAnalysis" class="bulk-analysis-bar">
      <el-button 
        type="primary" 
        @click="startBulkAnalysis" 
        :loading="bulkAnalyzing"
        :disabled="bulkAnalyzing"
      >
        AI 批量分析（逐方法分析）
      </el-button>
      <el-checkbox v-model="forceFreshBulk" style="margin-left: 10px" :disabled="bulkAnalyzing">
        强制全新分析
      </el-checkbox>
      
      <!-- 批量分析进度 -->
      <div v-if="bulkRunning" class="bulk-progress">
        <el-progress 
          :percentage="Math.round(bulkProgress * 100)" 
          :status="bulkProgress >= 1 ? 'success' : undefined"
          :stroke-width="16"
        />
        <span class="bulk-progress-text">
          {{ bulkCompleted }} / {{ bulkTotal }} 个方法
        </span>
      </div>
      
      <el-alert
        v-if="bulkComplete"
        title="✅ 批量分析完成"
        type="success"
        :closable="true"
        @close="bulkComplete = false"
        style="margin-top: 10px"
      />
      
      <el-alert
        v-if="bulkError"
        :title="'分析失败: ' + bulkError"
        type="error"
        :closable="true"
        @close="bulkError = ''"
        style="margin-top: 10px"
      />
    </div>
    
    <el-tree
      :data="data"
      :props="treeProps"
      node-key="id"
      default-expand-all
      :expand-on-click-node="false"
      v-loading="loading"
    >
      <template #default="{ node, data }">
        <span class="custom-tree-node">
          <el-icon><Connection /></el-icon>
          <span class="node-label">{{ data.label }}</span>
          
          <!-- 文档说明 (tooltip + inline) -->
          <el-tooltip 
            v-if="data.documentation && data.documentation !== 'None'" 
            :content="data.documentation" 
            placement="top" 
            :show-after="300"
            :hide-after="0"
            effect="dark"
            :popper-style="{ maxWidth: '500px', whiteSpace: 'pre-wrap' }"
          >
            <el-icon class="doc-icon"><InfoFilled /></el-icon>
          </el-tooltip>
          <el-tooltip
            v-else-if="data.documentation === undefined || data.documentation === null || data.documentation === 'None' || data.documentation === ''"
            content="开发未对函数做注解"
            placement="top"
            :show-after="300"
            :hide-after="0"
            effect="dark"
          >
            <el-icon class="doc-icon no-doc-icon"><WarningFilled /></el-icon>
          </el-tooltip>
          
          <!-- 变更类型标签 -->
          <el-tag v-if="data.changeType" size="small" :type="getChangeTypeTag(data.changeType)" style="margin-left: 6px">
            {{ data.changeType }}
          </el-tag>
          
          <!-- DAO/SQL 信息标签 -->
          <template v-if="data.daoInfo && data.daoInfo.sql_type">
            <el-tag size="small" :type="getSqlTypeTag(data.daoInfo.sql_type)" style="margin-left: 4px">
              {{ data.daoInfo.sql_type }}
            </el-tag>
            <el-tooltip 
              :content="getDaoDetailTooltip(data.daoInfo)" 
              placement="top" 
              :show-after="300"
              effect="dark"
              :popper-style="{ maxWidth: '500px', whiteSpace: 'pre-wrap' }"
            >
              <el-tag size="small" type="info" style="margin-left: 2px; cursor: help">
                {{ (data.daoInfo.tables || [])[0] || data.daoInfo.table_name || '?' }}
              </el-tag>
            </el-tooltip>
            <el-tag 
              v-if="data.daoInfo.risk_level" 
              size="small" 
              :type="getRiskTag(data.daoInfo.risk_level)" 
              style="margin-left: 2px"
            >
              {{ data.daoInfo.risk_level }}
            </el-tag>
          </template>
          
          <!-- 入口点 / API 路径标记 -->
          <el-tag v-if="data.rootType && isEntryType(data.rootType)" size="small" type="success" style="margin-left: 4px">
            🚪入口
          </el-tag>
          <template v-if="data.apiPaths && data.apiPaths.length > 0">
            <el-tag v-for="p in data.apiPaths" :key="p" size="small" style="margin-left: 2px">
              {{ p }}
            </el-tag>
          </template>
          
          <!-- 环检测标记 -->
          <el-tag v-if="data.isCyclic" size="small" type="danger" style="margin-left: 4px">
            🔄循环
          </el-tag>
          
          <!-- AI 分析状态标签（三类：方法 / 向上链 / 向下链） -->
          <el-tag 
            v-if="getNodeStatus(data)?.running_task_id" 
            size="small" 
            type="warning" 
            style="margin-left: 4px"
          >
            ⏳ 分析中
          </el-tag>
          <template v-else>
            <el-tag 
              v-if="getNodeStatus(data)?.method_status === 'analyzed'" 
              size="small" 
              type=""
              style="margin-left: 4px"
            >
              ✅ 方法分析
            </el-tag>
            <el-tag 
              v-if="getNodeStatus(data)?.upwards_chain_status === 'analyzed'" 
              size="small" 
              type="success"
              style="margin-left: 4px"
            >
              🔗 向上链分析
            </el-tag>
            <el-tag 
              v-if="getNodeStatus(data)?.downwards_chain_status === 'analyzed'" 
              size="small" 
              type="success"
              style="margin-left: 4px"
            >
              🔗 向下链分析
            </el-tag>
          </template>
          
          <!-- 操作按钮 (hover 显示) -->
          <span class="node-actions">
            <el-button 
              size="small" 
              type="primary" 
              text
              @click.stop="openAIConfig(data)"
            >
              [AI 分析]
            </el-button>
            <el-button 
              v-if="getNodeStatus(data)?.latest_method_result_id || getNodeStatus(data)?.latest_upwards_chain_result_id || getNodeStatus(data)?.latest_downwards_chain_result_id"
              size="small" 
              type="success"
              text
              @click.stop="viewResult(data)"
            >
              [查看结果]
            </el-button>
          </span>
        </span>
      </template>
    </el-tree>
    
    <el-empty v-if="!loading && data.length === 0" description="暂无数据" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Connection, InfoFilled, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import { useAIAnalysisStore } from '@/stores/aiAnalysis'
import { useSessionStore } from '@/stores/session'

const route = useRoute()
const router = useRouter()
const aiStore = useAIAnalysisStore()
const sessionStore = useSessionStore()

const props = defineProps<{
  data: any[]
  title?: string
  loading?: boolean
  showBulkAnalysis?: boolean
  direction?: string
}>()

const treeProps = {
  children: 'children',
  label: 'label'
}

// ========== AI 批量分析 ==========
const bulkAnalyzing = ref(false)
const forceFreshBulk = ref(false)
const bulkRunning = ref(false)
const bulkComplete = ref(false)
const bulkProgress = ref(0)
const bulkTotal = ref(0)
const bulkCompleted = ref(0)
const bulkError = ref('')
let bulkTaskId: string | null = null
let bulkPollTimer: number | null = null

const apiClient = axios.create({
  baseURL: 'http://127.0.0.1:8000/api',
  timeout: 300000,
  headers: { 'Content-Type': 'application/json' }
})

// 轮询批量任务进度 + Tree 节点状态
const startBatchPolling = (taskId: string) => {
  const poll = async () => {
    try {
      const res = await apiClient.get(`/analysis/tasks/${taskId}`)
      const task = res.data
      bulkProgress.value = task.progress || 0
      bulkCompleted.value = task.completed_methods || 0
      bulkTotal.value = task.total_methods || 0
      
      // 每轮同步刷新 Tree 节点标签
      await loadNodesStatus()
      
      if (task.status === 'completed') {
        stopBatchPolling()
        bulkAnalyzing.value = false
        bulkRunning.value = false
        bulkComplete.value = true
        await loadNodesStatus() // 最后一次刷新确保全部更新
      } else if (task.status === 'failed') {
        stopBatchPolling()
        bulkAnalyzing.value = false
        bulkRunning.value = false
        bulkError.value = task.error_message || '未知错误'
      }
    } catch (err: any) {
      console.error('批量任务轮询失败:', err)
    }
  }
  
  poll()
  bulkPollTimer = window.setInterval(poll, 2000)
}

const stopBatchPolling = () => {
  if (bulkPollTimer) {
    clearInterval(bulkPollTimer)
    bulkPollTimer = null
  }
  bulkTaskId = null
}

onMounted(() => {
  loadNodesStatus()
})

// 数据变化时重新加载节点状态
watch(() => props.data, () => {
  loadNodesStatus()
}, { deep: true })

onUnmounted(() => {
  stopBatchPolling()
})

const startBulkAnalysis = async () => {
  const baseline = route.query.baseline as string
  const version = route.query.version as string
  if (!baseline || !version) {
    ElMessage.warning('请先选择基线和版本')
    return
  }
  
  // 收集 Tree 中所有方法
  const nodes = collectNodeKeys(props.data)
  if (nodes.length === 0) {
    ElMessage.warning('Tree 中没有可分析的方法')
    return
  }
  
  bulkAnalyzing.value = true
  bulkRunning.value = true
  bulkComplete.value = false
  bulkError.value = ''
  bulkProgress.value = 0
  bulkCompleted.value = 0
  bulkTotal.value = nodes.length
  
  try {
    const response = await apiClient.post('/analysis/batch-methods', {
      baseline,
      version,
      direction: props.direction || 'upwards',
      force_fresh: forceFreshBulk.value,
      methods: nodes
    })
    
    bulkTaskId = response.data.task_id
    if (bulkTaskId) {
      startBatchPolling(bulkTaskId)
    }
    ElMessage.success(response.data.message)
  } catch (err: any) {
    bulkAnalyzing.value = false
    bulkRunning.value = false
    if (err.response?.status === 409) {
      bulkError.value = '已有 LLM 分析正在执行中，请等待完成后再试'
      ElMessage.warning(bulkError.value)
    } else {
      bulkError.value = err.response?.data?.detail || err.message || '未知错误'
      ElMessage.error('分析失败')
    }
  }
}

// ========== AI 节点状态 ==========

/**
 * 解析节点标签中的类名和方法名
 */
const parseNodeInfo = (data: any) => {
  const label = data.label || ''
  // 标签格式: ClassName.methodSignature  📝...
  const match = label.match(/^([\w.]+)\.(\w+)\(?/)
  if (match) {
    return { class_name: match[1], method_name: match[2] }
  }
  return { class_name: '', method_name: '' }
}

/**
 * 递归收集所有叶子节点的类名/方法名，用于批量查询
 */
const collectNodeKeys = (treeData: any[]): any[] => {
  const nodes: any[] = []
  const seen = new Set<string>()
  const walk = (items: any[]) => {
    for (const item of items) {
      if (item.label && !item.daoInfo) {
        const info = parseNodeInfo(item)
        const key = `${info.class_name}.${info.method_name}`
        if (info.class_name && info.method_name && !seen.has(key)) {
          seen.add(key)
          nodes.push({
            class_name: info.class_name,
            method_name: info.method_name,
            change_type: item.changeType || 'UNKNOWN'
          })
        }
      }
      if (item.children) walk(item.children)
    }
  }
  walk(treeData)
  return nodes
}

/**
 * 加载节点分析状态
 */
const loadNodesStatus = async () => {
  const baseline = route.query.baseline as string
  const version = route.query.version as string
  if (!baseline || !version || !props.data || props.data.length === 0) return
  
  const nodes = collectNodeKeys(props.data)
  if (nodes.length === 0) return
  
  await aiStore.loadNodesStatus(baseline, version, nodes)
}

/**
 * 获取节点状态（兼容解析）
 */
const getNodeStatus = (data: any) => {
  if (!data.label || data.daoInfo) return undefined
  const info = parseNodeInfo(data)
  if (!info.class_name || !info.method_name) return undefined
  return aiStore.getNodeStatus(info.class_name, info.method_name)
}

/**
 * 在新标签页中打开 AI 分析配置页
 */
const openAIConfig = (data: any) => {
  const info = parseNodeInfo(data)
  const baseline = route.query.baseline as string
  const version = route.query.version as string
  
  const resolved = router.resolve({
    name: 'AIAnalysisConfig',
    params: { taskId: route.params.taskId as string },
    query: {
      class_name: info.class_name,
      method_name: info.method_name,
      change_type: data.changeType || 'UNKNOWN',
      signature: data.label || '',
      baseline,
      version,
      direction: props.direction || 'upwards'
    }
  })
  window.open(resolved.href, '_blank')
}

/**
 * 在新标签页中查看分析结果
 */
const viewResult = (data: any) => {
  const status = getNodeStatus(data)
  // 根据当前 Tree 方向优先选择对应方向的结果
  const direction = props.direction || 'upwards'
  let resultId = direction === 'downwards'
    ? status?.latest_downwards_chain_result_id
    : status?.latest_upwards_chain_result_id
  if (!resultId) {
    resultId = status?.latest_method_result_id
  }
  if (resultId) {
    const resolved = router.resolve({
      name: 'AIAnalysisResult',
      params: {
        taskId: route.params.taskId as string,
        resultId
      },
      query: {
        baseline: route.query.baseline as string,
        version: route.query.version as string,
        direction: direction,
        class_name: parseNodeInfo(data).class_name,
        method_name: parseNodeInfo(data).method_name
      }
    })
    window.open(resolved.href, '_blank')
  }
}

// ========== 标签颜色 ==========
const isEntryType = (type: string) => {
  const entryTypes = [
    'HTTP_API', 'SCHEDULED_TASK', 'EVENT_LISTENER',
    'MESSAGE_CONSUMER', 'CONTROLLER_BY_CONVENTION'
  ]
  return entryTypes.includes(type)
}

const getChangeTypeTag = (type: string) => {
  const map: Record<string, any> = {
    ADDED: 'success',
    MODIFIED: 'warning',
    DELETED: 'danger',
    UNCHANGED: 'info'
  }
  return map[type] || 'info'
}

const getSqlTypeTag = (type: string) => {
  const map: Record<string, any> = {
    SELECT: '',
    INSERT: 'success',
    UPDATE: 'warning',
    DELETE: 'danger'
  }
  return map[type] || 'info'
}

const getRiskTag = (level: string) => {
  const map: Record<string, any> = {
    LOW: 'info',
    MEDIUM: 'warning',
    HIGH: 'danger',
    CRITICAL: 'danger'
  }
  return map[level] || 'info'
}

const getDaoDetailTooltip = (di: any) => {
  const parts = []
  const sqlContent = di.sql_statement || di.sql_content || ''
  if (sqlContent) parts.push('SQL: ' + sqlContent.replace(/\n/g, ' '))
  if (di.tables && di.tables.length) parts.push('Tables: ' + di.tables.join(', '))
  if (di.table_name && (!di.tables || di.tables.length === 0)) parts.push('Table: ' + di.table_name)
  if (di.entity_name) parts.push('Entity: ' + di.entity_name)
  if (di.warning) parts.push('Warning: ' + di.warning)
  if (di.performance_level) parts.push('Performance: ' + di.performance_level)
  return parts.join('\n') || 'No details'
}
</script>

<style scoped>
.call-chain-tree {
  padding: 20px;
}

.call-chain-tree h3 {
  margin-bottom: 15px;
  color: #409EFF;
}

.custom-tree-node {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.node-label {
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 13px;
}

.doc-icon {
  color: #909399;
  font-size: 14px;
  cursor: help;
  flex-shrink: 0;
}

.no-doc-icon {
  color: #E6A23C;
}

.node-actions {
  opacity: 0;
  transition: opacity 0.15s;
  margin-left: 4px;
}

.custom-tree-node:hover .node-actions {
  opacity: 1;
}

.bulk-analysis-bar {
  margin-bottom: 15px;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 6px;
}

.bulk-progress {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.bulk-progress-text {
  font-size: 13px;
  color: #606266;
  white-space: nowrap;
}
</style>
