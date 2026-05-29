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
      
      <!-- 视图切换 -->
      <el-tabs v-model="activeTab" type="border-card" v-loading="loading">
        <el-tab-pane label="向上调用链" name="upstream">
          <CallChainTree 
            :data="upstreamData" 
            title="向上调用链（谁调用了这个方法）"
            :loading="loading"
            :showBulkAnalysis="true"
            direction="upwards"
          />
        </el-tab-pane>
        
        <el-tab-pane label="向下调用链" name="downstream">
          <CallChainTree 
            :data="downstreamData" 
            title="向下调用链（这个方法调用了谁）"
            :loading="loading"
          />
        </el-tab-pane>
        
        <el-tab-pane label="文本视图" name="text">
          <TextViewer 
            :upwardsContent="upwardsText"
            :downwardsContent="downwardsText"
            :loading="loading" 
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
import { getUpwardsChains, getDownwardsChains, getUpwardsText, getDownwardsText } from '@/api/analysis'
import { useSessionStore } from '@/stores/session'
import BaselineSelector from '@/components/BaselineSelector.vue'
import CallChainTree from '@/components/CallChainTree.vue'
import TextViewer from '@/components/TextViewer.vue'
import SqlAnalysisView from '@/components/SqlAnalysisView.vue'

const route = useRoute()
const taskId = route.params.taskId as string
const sessionStore = useSessionStore()

const taskInfo = ref<any>(null)
const loading = ref(false)
const activeTab = ref('upstream')
const lockedBaseline = ref('')

// 分析结果数据
const upstreamData = ref<any[]>([])
const downstreamData = ref<any[]>([])
const upwardsText = ref('')
const downwardsText = ref('')

const getStatusType = (status: string) => {
  const typeMap: Record<string, any> = {
    pending: 'info',
    running: 'warning',
    completed: 'success',
    failed: 'danger'
  }
  return typeMap[status] || 'info'
}

// 基线变化处理
const handleBaselineChange = async (baseline: string, version: string) => {
  sessionStore.setBaselineAndVersion(baseline, version)
  await loadAnalysisData(baseline, version)
}

// 加载分析数据
const loadAnalysisData = async (baseline: string, version: string) => {
  loading.value = true
  // 先清空旧数据，避免切换版本时残留
  upstreamData.value = []
  downstreamData.value = []
  upwardsText.value = ''
  downwardsText.value = ''
  
  try {
    // 并行加载所有数据
    const [upwardsRes, downwardsRes, upwardsTextRes, downwardsTextRes] = await Promise.all([
      getUpwardsChains(baseline, version).catch(() => null),
      getDownwardsChains(baseline, version).catch(() => null),
      getUpwardsText(baseline, version).catch(() => null),
      getDownwardsText(baseline, version).catch(() => null)
    ])
    
    let hasData = false
    
    // 处理向上调用链（入口展开）
    if (upwardsRes?.data) {
      upstreamData.value = convertUpwardsChainsToTree(upwardsRes.data.impact_chains || [])
      hasData = true
    }
    
    // 处理向下调用链（递归展开完整链结构）
    if (downwardsRes?.data) {
      downstreamData.value = convertDownwardsChainsToTree(downwardsRes.data.call_chains || [])
      hasData = true
    }
    
    // 处理文本视图
    if (upwardsTextRes?.data) {
      upwardsText.value = upwardsTextRes.data.content || ''
      hasData = true
    }
    if (downwardsTextRes?.data) {
      downwardsText.value = downwardsTextRes.data.content || ''
      hasData = true
    }
    
    if (hasData) {
      ElMessage.success('数据加载成功')
    } else {
      ElMessage.warning('该版本暂无分析数据')
    }
  } catch (error) {
    console.error('加载分析数据失败:', error)
    ElMessage.error('加载分析数据失败')
  } finally {
    loading.value = false
  }
}

// 构建树节点标签（v4.1：含 documentation 摘要）
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
  
  // 添加 documentation 摘要（截取前60字符）
  const doc = documentation || altDocumentation || ''
  if (doc && typeof doc === 'string' && doc.trim() && doc.trim() !== 'None') {
    const docShort = doc.trim().replace(/\n/g, ' ').substring(0, 60)
    label += `  📝${docShort}${doc.trim().length > 60 ? '...' : ''}`
  } else {
    // documentation 为 None 或空时，显示提示
    label += `  ⚠️开发未对函数做注解`
  }
  
  return label
}

// 向上调用链：递归展开 chain 树结构，完整展示谁调用了谁
const convertUpwardsChainsToTree = (chains: any[]) => {
  return chains.map((chain, index) => {
    const mi = chain.method_info || {}
    const ch = chain.chain || {}
    
    // 根节点：变更方法
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
  })
}

// 向上链递归构建子节点（调用者）
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
    
    // 入口节点：添加 API 路径标记
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

// 向下调用链：递归展开 chain.children 结构，保留 dao_info
const convertDownwardsChainsToTree = (chains: any[]) => {
  return chains.map((chain, index) => {
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
  })
}

const buildDownwardsChildren = (children: any[]): any[] => {
  if (!children || !Array.isArray(children)) return []
  return children.map((child: any) => {
    let label = buildTreeNodeLabel(
      child.class_name, child.method_name,
      child.method_signature, child.change_type,
      child.documentation
    )
    
    // 环检测标记
    if (child.is_cyclic) {
      label += '  🔄循环'
    }
    
    const di = child.dao_info
    const grandChildren = buildDownwardsChildren(child.children || [])
    
    // 若当前节点有 dao_info，合成一个 SQL 摘要子节点插在最前面
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
      // 构建标签子节点（类型、表名、风险等级合并为一行）
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

const loadTaskInfo = async () => {
  if (!taskId) return
  
  loading.value = true
  try {
    const response = await taskApi.getTask(taskId)
    taskInfo.value = response.data
    
    // 从任务锁定基线版本，允许多版本切换（使用完整标签，后端自动映射）
    if (taskInfo.value?.tag_old) {
      lockedBaseline.value = taskInfo.value.tag_old
      // 若 session 中无基线/版本，用任务的完整标签填充
      if (!sessionStore.selectedBaseline) {
        sessionStore.setBaselineAndVersion(
          taskInfo.value.tag_old,
          taskInfo.value.tag_new || ''
        )
      }
    }
  } catch (error) {
    console.error('加载任务信息失败:', error)
  } finally {
    loading.value = false
  }
}

// Tab 切换时同步到会话
watch(activeTab, (newTab) => {
  sessionStore.setActiveTab(newTab)
})

onMounted(() => {
  loadTaskInfo()
  sessionStore.initFromUrl()
  
  // 如果会话中已有基线和版本，自动加载数据
  if (sessionStore.selectedBaseline && sessionStore.selectedVersion) {
    loadAnalysisData(sessionStore.selectedBaseline, sessionStore.selectedVersion)
  }
  
  // 恢复上次的 Tab
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
</style>
