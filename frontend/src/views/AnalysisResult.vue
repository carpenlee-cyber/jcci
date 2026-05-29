<template>
  <div class="analysis-result">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>📊 分析结果</h2>
          <el-button @click="$router.push('/tasks')">
            <el-icon><Back /></el-icon>
            返回列表
          </el-button>
        </div>
      </template>

      <!-- 基线选择器 -->
      <BaselineSelector
        :initialBaseline="lockedBaseline || sessionStore.selectedBaseline"
        :initialVersion="sessionStore.selectedVersion"
        :lockedBaseline="!!lockedBaseline"
        @change="handleBaselineChange"
      />

      <!-- 任务信息 -->
      <el-descriptions :column="3" border v-if="taskInfo">
        <el-descriptions-item label="任务ID">{{ taskInfo.task_id }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="getStatusType(taskInfo.status)">{{ taskInfo.status }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="进度">
          <el-progress :percentage="taskInfo.progress" />
        </el-descriptions-item>
        <el-descriptions-item label="Git仓库" :span="2">{{ taskInfo.git_url }}</el-descriptions-item>
        <el-descriptions-item label="基线 → 目标">{{ taskInfo.tag_old }} → {{ taskInfo.tag_new }}</el-descriptions-item>
      </el-descriptions>

      <el-divider />

      <!-- 方向切换 + 方法摘要表格 -->
      <div class="direction-bar">
        <el-radio-group v-model="chainDirection" size="small" @change="handleDirectionChange">
          <el-radio-button value="upwards">⬆ 向上调用链（谁调用了我）</el-radio-button>
          <el-radio-button value="downwards">⬇ 向下调用链（我调用了谁）</el-radio-button>
        </el-radio-group>
      </div>

      <MethodSummaryTable
        :methods="chainMethods"
        :total="chainMethodsTotal"
        :loading="summaryLoading"
        :selectedKey="selectedMethodKey"
        @select="handleMethodSelect"
      />

      <!-- 选中方法的调用链详情 -->
      <div v-if="selectedChainData.length > 0" class="chain-detail">
        <el-divider />
        <div class="detail-header">
          <h4>{{ chainDirection === 'upwards' ? '⬆ 向上调用链' : '⬇ 向下调用链' }} 详情</h4>
          <el-button size="small" text @click="clearSelection">✕ 关闭</el-button>
        </div>
        <CallChainTree
          :data="selectedChainData"
          :title="selectedMethodKey || ''"
          :loading="chainLoading"
          :showBulkAnalysis="chainDirection === 'upwards'"
          :direction="chainDirection"
        />
      </div>

      <el-divider />

      <!-- 文本视图 + SQL -->
      <el-tabs v-model="activeTab" type="border-card" v-loading="textLoading">
        <el-tab-pane label="文本视图" name="text">
          <TextViewer
            :upwardsContent="upwardsText"
            :downwardsContent="downwardsText"
            :loading="textLoading"
          />
        </el-tab-pane>

        <el-tab-pane label="SQL分析" name="sql">
          <SqlAnalysisView />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Back } from '@element-plus/icons-vue'
import { taskApi } from '@/api/task'
import {
  getUpwardsChains,
  getDownwardsChains,
  getUpwardsText,
  getDownwardsText,
  getChainMethods,
  type ChainMethodSummary
} from '@/api/analysis'
import { useSessionStore } from '@/stores/session'
import BaselineSelector from '@/components/BaselineSelector.vue'
import CallChainTree from '@/components/CallChainTree.vue'
import TextViewer from '@/components/TextViewer.vue'
import SqlAnalysisView from '@/components/SqlAnalysisView.vue'
import MethodSummaryTable from '@/components/MethodSummaryTable.vue'

const route = useRoute()
const taskId = route.params.taskId as string
const sessionStore = useSessionStore()

const taskInfo = ref<any>(null)
const activeTab = ref('text')
const lockedBaseline = ref('')

// ── 调用链摘要 & 详情 ──
const chainDirection = ref<'upwards' | 'downwards'>('upwards')
const chainMethods = ref<ChainMethodSummary[]>([])
const chainMethodsTotal = ref(0)
const summaryLoading = ref(false)
const selectedMethodKey = ref('')
const selectedChainData = ref<any[]>([])
const chainLoading = ref(false)

// 缓存全量链数据，避免重复请求
const cachedChains = ref<Record<string, any[]>>({})

// ── 文本视图 ──
const upwardsText = ref('')
const downwardsText = ref('')
const textLoading = ref(false)

const getStatusType = (status: string) => {
  const typeMap: Record<string, any> = {
    pending: 'info',
    running: 'warning',
    completed: 'success',
    failed: 'danger'
  }
  return typeMap[status] || 'info'
}

// 基线变化处理 → 重新加载摘要
const handleBaselineChange = async (baseline: string, version: string) => {
  sessionStore.setBaselineAndVersion(baseline, version)
  clearSelection()
  cachedChains.value = {}
  await loadSummary(baseline, version)
  loadTexts(baseline, version)
}

// ── 加载变更方法摘要（仅元信息，极轻量） ──
const loadSummary = async (baseline: string, version: string) => {
  summaryLoading.value = true
  chainMethods.value = []
  chainMethodsTotal.value = 0

  try {
    const dir = chainDirection.value
    const res = await getChainMethods(baseline, version, dir)
    if (res?.data) {
      chainMethods.value = res.data.methods || []
      chainMethodsTotal.value = res.data.total || chainMethods.value.length
    }
    if (chainMethods.value.length > 0) {
      ElMessage.success(`已加载 ${chainMethodsTotal.value} 个变更方法`)
    } else {
      ElMessage.warning('该版本暂无变更方法数据')
    }
  } catch (error) {
    console.error('加载方法摘要失败:', error)
    ElMessage.error('加载方法摘要失败')
  } finally {
    summaryLoading.value = false
  }
}

// ── 方向切换 ──
const handleDirectionChange = () => {
  const baseline = sessionStore.selectedBaseline
  const version = sessionStore.selectedVersion
  if (baseline && version) {
    clearSelection()
    loadSummary(baseline, version)
  }
}

// ── 选择方法 → 加载该方法的完整调用链详情 ──
const handleMethodSelect = async (method: ChainMethodSummary) => {
  const key = `${method.class_name}.${method.method_name}`
  if (selectedMethodKey.value === key) return // 已选中

  const baseline = sessionStore.selectedBaseline
  const version = sessionStore.selectedVersion
  if (!baseline || !version) return

  selectedMethodKey.value = key
  chainLoading.value = true
  selectedChainData.value = []

  try {
    // 优先从缓存取全量链数据
    const cacheKey = `${baseline}:${version}:${chainDirection.value}`
    let chains: any[]
    if (cachedChains.value[cacheKey]) {
      chains = cachedChains.value[cacheKey]
    } else {
      const res = chainDirection.value === 'upwards'
        ? await getUpwardsChains(baseline, version)
        : await getDownwardsChains(baseline, version)
      chains = chainDirection.value === 'upwards'
        ? (res?.data?.impact_chains || [])
        : (res?.data?.call_chains || [])
      cachedChains.value[cacheKey] = chains
    }

    // 找到匹配的单条链并转为树（仅 1 条！）
    const matched = chains.find((c: any) => {
      const mi = c.method_info || {}
      return mi.class_name === method.class_name && mi.method_name === method.method_name
    })

    if (matched) {
      selectedChainData.value = chainDirection.value === 'upwards'
        ? [convertSingleUpwardsChain(matched, 0)]
        : [convertSingleDownwardsChain(matched, 0)]
    } else {
      ElMessage.warning('未找到该方法调用链数据')
    }
  } catch (error) {
    console.error('加载调用链详情失败:', error)
    ElMessage.error('加载调用链详情失败')
  } finally {
    chainLoading.value = false
  }
}

const clearSelection = () => {
  selectedMethodKey.value = ''
  selectedChainData.value = []
}

// ── 文本视图（独立加载，不阻塞摘要） ──
const loadTexts = async (baseline: string, version: string) => {
  textLoading.value = true
  const [upRes, downRes] = await Promise.all([
    getUpwardsText(baseline, version).catch(() => null),
    getDownwardsText(baseline, version).catch(() => null)
  ])
  upwardsText.value = upRes?.data?.content || ''
  downwardsText.value = downRes?.data?.content || ''
  textLoading.value = false
}

// ── 树构建（与原逻辑一致，但每次只构建 1 条链） ──
const buildTreeNodeLabel = (
  className: string,
  methodName: string,
  signature: string,
  changeType: string,
  documentation?: string,
  altDocumentation?: string
): string => {
  const cls = className || '?'
  const mName = methodName || '?'
  const sig = signature || `${mName}()`
  let label = `${cls}.${sig}`
  const doc = documentation || altDocumentation || ''
  if (doc && typeof doc === 'string' && doc.trim() && doc.trim() !== 'None') {
    const docShort = doc.trim().replace(/\n/g, ' ').substring(0, 60)
    label += `  📝${docShort}${doc.trim().length > 60 ? '...' : ''}`
  }
  // ⚠️提示已由 CallChainTree tooltip 处理，不追加内联文本
  return label
}

const buildUpwardsChildren = (children: any[], isFirstLevel: boolean = false): any[] => {
  if (!children || !Array.isArray(children)) return []
  return children.map((child: any) => {
    const isEntry = child.root_type && [
      'HTTP_API', 'SCHEDULED_TASK', 'EVENT_LISTENER',
      'MESSAGE_CONSUMER', 'CONTROLLER_BY_CONVENTION'
    ].includes(child.root_type)
    const label = buildTreeNodeLabel(
      child.class_name, child.method_name,
      child.method_signature, child.change_type,
      child.documentation
    )
    let finalLabel = label
    if (isEntry && child.api_paths && child.api_paths.length > 0) {
      finalLabel += `  [${child.api_paths.join(', ')}] 🚪`
    } else if (isEntry) {
      finalLabel += `  [${child.root_type}] 🚪`
    }
    return {
      id: child.node_id || `up-node-${Math.random()}`,
      label: finalLabel,
      changeType: child.change_type,
      documentation: child.documentation || '',
      apiPaths: child.api_paths || [],
      rootType: child.root_type,
      isCyclic: child.is_cyclic || child.root_type === 'CYCLIC',
      children: buildUpwardsChildren(child.children || [])
    }
  })
}

const convertSingleUpwardsChain = (chain: any, index: number) => {
  const mi = chain.method_info || {}
  const ch = chain.chain || {}
  const rootLabel = buildTreeNodeLabel(
    mi.class_name, mi.method_name,
    (ch.children || []).length > 0 ? ch.method_signature : mi.method_signature,
    mi.change_type, mi.documentation, ch.documentation
  )
  return {
    id: `up-${index}`,
    label: rootLabel,
    changeType: mi.change_type,
    documentation: mi.documentation || ch.documentation || '',
    children: buildUpwardsChildren(ch.children || [], true)
  }
}

const buildDownwardsChildren = (children: any[]): any[] => {
  if (!children || !Array.isArray(children)) return []
  return children.map((child: any) => {
    let label = buildTreeNodeLabel(
      child.class_name, child.method_name,
      child.method_signature, child.change_type,
      child.documentation
    )
    if (child.is_cyclic) {
      label += '  🔄循环'
    }
    const di = child.dao_info
    const grandChildren = buildDownwardsChildren(child.children || [])
    if (di && di.sql_type) {
      const baseId = (child.node_id || `node-${Math.random()}`) + '-sql'
      const sqlContent = di.sql_statement || di.sql_content || ''
      let sqlLabel = ''
      if (sqlContent) {
        const sqlPreview = sqlContent.replace(/\n/g, ' ').substring(0, 150)
        sqlLabel = `→ 🗄️${di.sql_type}: ${sqlPreview}${sqlContent.length > 150 ? '...' : ''}`
      } else {
        const table = (di.tables || [])[0] || di.table_name || ''
        sqlLabel = `→ 🗄️${di.sql_type}${table ? ' on ' + table : ''}`
      }
      const tagParts: string[] = []
      if (di.sql_type) tagParts.push(`🏷️${di.sql_type}`)
      const tableName = (di.tables || [])[0] || di.table_name || ''
      if (tableName) tagParts.push(`📦${tableName}`)
      if (di.risk_level) tagParts.push(`⚠️${di.risk_level}`)
      const tagChildren: any[] = []
      if (tagParts.length > 0) {
        tagChildren.push({
          id: `${baseId}-tags`,
          label: tagParts.join('  |  '),
          changeType: null, documentation: '', daoInfo: null, isCyclic: false, children: []
        })
      }
      grandChildren.unshift({
        id: baseId,
        label: sqlLabel,
        changeType: null,
        documentation: '',
        daoInfo: null,
        isCyclic: false,
        children: tagChildren
      })
    }
    return {
      id: child.node_id || `node-${Math.random()}`,
      label,
      changeType: child.change_type,
      documentation: child.documentation || '',
      daoInfo: null,
      isCyclic: child.is_cyclic || false,
      children: grandChildren
    }
  })
}

const convertSingleDownwardsChain = (chain: any, index: number) => {
  const mi = chain.method_info || {}
  const ch = chain.chain || {}
  const rootLabel = buildTreeNodeLabel(
    mi.class_name, mi.method_name,
    (ch.children || []).length > 0 ? ch.method_signature : mi.method_signature,
    mi.change_type, mi.documentation, ch.documentation
  )
  return {
    id: `down-${index}`,
    label: rootLabel,
    changeType: mi.change_type,
    documentation: mi.documentation || ch.documentation || '',
    children: buildDownwardsChildren(ch.children || [])
  }
}

// ── 任务信息 ──
const loadTaskInfo = async () => {
  if (!taskId) return
  try {
    const response = await taskApi.getTask(taskId)
    taskInfo.value = response.data
    if (taskInfo.value?.tag_old) {
      lockedBaseline.value = taskInfo.value.tag_old
      if (!sessionStore.selectedBaseline) {
        sessionStore.setBaselineAndVersion(
          taskInfo.value.tag_old,
          taskInfo.value.tag_new || ''
        )
      }
    }
  } catch (error) {
    console.error('加载任务信息失败:', error)
  }
}

// Tab 切换同步到会话
watch(activeTab, (newTab) => {
  sessionStore.setActiveTab(newTab)
})

onMounted(async () => {
  await loadTaskInfo()
  sessionStore.initFromUrl()

  if (sessionStore.selectedBaseline && sessionStore.selectedVersion) {
    // 优先加载摘要（秒级响应），文本在后台加载
    await loadSummary(sessionStore.selectedBaseline, sessionStore.selectedVersion)
    loadTexts(sessionStore.selectedBaseline, sessionStore.selectedVersion)
  }

  if (sessionStore.activeTab) {
    activeTab.value = sessionStore.activeTab
  }
})
</script>

<style scoped>
.analysis-result {
  max-width: 1400px;
  margin: 0 auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-header h2 {
  margin: 0;
}

.direction-bar {
  margin-bottom: 12px;
}

.chain-detail {
  margin-top: 4px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.detail-header h4 {
  margin: 0;
  color: #409EFF;
}
</style>
