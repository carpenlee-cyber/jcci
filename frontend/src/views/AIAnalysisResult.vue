<template>
  <div class="ai-result-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>📋 AI 分析结果</h2>
          <div>
            <el-button @click="backToAnalysis">
              <el-icon><Back /></el-icon>
              返回分析结果
            </el-button>
          </div>
        </div>
      </template>

      <!-- 三类分析结果切换标签 -->
      <el-tabs v-model="activeResultType" type="border-card" @tab-change="switchResultType">
        <el-tab-pane label="✅ 方法分析" name="method" :disabled="!resultIds.method">
          <template #label>
            <span>✅ 方法分析</span>
          </template>
        </el-tab-pane>
        <el-tab-pane label="🔗 向上调用链分析" name="upwards_chain" :disabled="!resultIds.upwards_chain">
          <template #label>
            <span>🔗 向上调用链分析</span>
          </template>
        </el-tab-pane>
        <el-tab-pane label="🔗 向下调用链分析" name="downwards_chain" :disabled="!resultIds.downwards_chain">
          <template #label>
            <span>🔗 向下调用链分析</span>
          </template>
        </el-tab-pane>
      </el-tabs>

      <!-- 元信息 -->
      <el-descriptions :column="3" border v-if="result" style="margin-top: 16px">
        <el-descriptions-item label="方法">
          {{ result.class_name }}.{{ result.method_name }}
        </el-descriptions-item>
        <el-descriptions-item label="分析类型">
          <el-tag :type="resultTypeTag(activeResultType)" size="small">
            {{ resultTypeLabel(activeResultType) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="模型">
          {{ result.model_name || 'N/A' }}
        </el-descriptions-item>
        <el-descriptions-item label="耗时">
          {{ (result.analysis_duration || 0).toFixed(2) }}s
        </el-descriptions-item>
        <el-descriptions-item label="来源">
          <el-tag v-if="result.from_cache" type="info" size="small">♻️ 缓存</el-tag>
          <el-tag v-else type="success" size="small">🆕 全新分析</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="时间">
          {{ result.created_at || 'N/A' }}
        </el-descriptions-item>
      </el-descriptions>

      <el-divider />

      <!-- 子结果切换标签（链路分析模式） -->
      <template v-if="subResults.length > 1">
        <el-tabs v-model="activeSubTab" type="card">
          <el-tab-pane label="聚合分析" name="aggregation" />
          <el-tab-pane
            v-for="(sub, idx) in subResults"
            :key="sub.result_id"
            :label="`${sub.class_name?.split('.').pop() || ''}.${sub.method_name || ''}`"
            :name="sub.result_id"
          />
        </el-tabs>
      </template>

      <!-- Markdown 内容 -->
      <div class="markdown-content" v-html="renderedMarkdown" v-loading="loading"></div>

      <el-empty v-if="!loading && !displayContent" description="暂无分析结果" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Back } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { useAIAnalysisStore } from '@/stores/analysisStore'
import { getAnalysisResult as fetchResult, getNodesStatus } from '@/api/aiAnalysis'

const route = useRoute()
const router = useRouter()
const store = useAIAnalysisStore()

const resultId = route.params.resultId as string
const aiTaskId = (route.query.aiTaskId as string) || ''
const className = (route.query.class_name as string) || ''
const methodName = (route.query.method_name as string) || ''
const baseline = (route.query.baseline as string) || ''
const version = (route.query.version as string) || ''
const loading = ref(false)
const result = ref<any>(null)
const activeSubTab = ref('aggregation')
const subResults = ref<any[]>([])

// 三类结果 ID
const resultIds = reactive({
  method: '' as string | null,
  upwards_chain: '' as string | null,
  downwards_chain: '' as string | null
})
const activeResultType = ref('method')

const resultTypeLabel = (type: string) => {
  const map: Record<string, string> = {
    method: '方法分析',
    upwards_chain: '向上调用链分析',
    downwards_chain: '向下调用链分析'
  }
  return map[type] || type
}

const resultTypeTag = (type: string) => {
  const map: Record<string, any> = {
    method: '',
    upwards_chain: 'success',
    downwards_chain: 'success'
  }
  return map[type] || ''
}

const displayContent = computed(() => {
  if (activeSubTab.value === 'aggregation') {
    return result.value?.analysis_result || ''
  }
  const sub = subResults.value.find(s => s.result_id === activeSubTab.value)
  return sub?.analysis_result || result.value?.analysis_result || ''
})

const renderedMarkdown = computed(() => {
  if (!displayContent.value) return ''
  return marked(displayContent.value)
})


const backToAnalysis = () => {
  router.push({
    name: 'AnalysisResult',
    params: { taskId: route.params.taskId as string }
  })
}

const goToProgress = () => {
  if (aiTaskId) {
    router.push({
      name: 'AIAnalysisProgress',
      params: { taskId: route.params.taskId as string, aiTaskId }
    })
  }
}

/**
 * 切换结果类型时加载对应结果
 */
const switchResultType = async (type: string) => {
  await loadResultForType(type)
}

/**
 * 加载指定类型的结果
 */
const loadResultForType = async (type: string) => {
  const rid = resultIds[type as keyof typeof resultIds]
  if (!rid) {
    result.value = null
    subResults.value = []
    activeSubTab.value = 'aggregation'
    return
  }
  loading.value = true
  try {
    const res = await fetchResult(rid)
    result.value = res.data
    // 填充子结果列表（用于链分析的聚合/子方法切换）
    subResults.value = res.data.sub_results || []
    activeSubTab.value = 'aggregation'
  } catch (err) {
    console.error('加载结果失败:', err)
    result.value = null
    subResults.value = []
  } finally {
    loading.value = false
  }
}

/**
 * 从 nodes-status API 加载所有三类结果 ID
 */
const loadAllResultIds = async () => {
  if (!className || !methodName || !baseline || !version) return
  
  try {
    const nodes = [{
      class_name: className,
      method_name: methodName,
      change_type: 'UNKNOWN'
    }]
    const res = await getNodesStatus(baseline, version, nodes)
    if (res.data.nodes && res.data.nodes.length > 0) {
      const node = res.data.nodes[0]
      resultIds.method = node.latest_method_result_id || null
      resultIds.upwards_chain = node.latest_upwards_chain_result_id || null
      resultIds.downwards_chain = node.latest_downwards_chain_result_id || null
    }
  } catch (err) {
    console.error('加载结果 ID 失败:', err)
  }
}

const loadResult = async () => {
  // 先加载方法信息确定所有结果 ID
  await loadAllResultIds()
  
  // 确定初始显示的 tab
  let initialType = 'method'
  if (resultId && resultIds.method && resultId !== resultIds.method) {
    // 如果传入的 resultId 不是 method，尝试匹配
    if (resultIds.upwards_chain === resultId) initialType = 'upwards_chain'
    else if (resultIds.downwards_chain === resultId) initialType = 'downwards_chain'
  } else if (!resultIds.method) {
    // method 无结果，选择第一个可用的
    if (resultIds.upwards_chain) initialType = 'upwards_chain'
    else if (resultIds.downwards_chain) initialType = 'downwards_chain'
  }
  
  activeResultType.value = initialType
  await loadResultForType(initialType)
}

onMounted(() => {
  loadResult()
})
</script>

<style scoped>
.ai-result-page {
  max-width: 1000px;
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

.markdown-content {
  padding: 20px;
  line-height: 1.8;
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3) {
  margin-top: 24px;
  margin-bottom: 12px;
  color: #303133;
}

.markdown-content :deep(h1) { font-size: 1.6em; border-bottom: 2px solid #409EFF; padding-bottom: 6px; }
.markdown-content :deep(h2) { font-size: 1.3em; }
.markdown-content :deep(h3) { font-size: 1.1em; }

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  padding-left: 24px;
}

.markdown-content :deep(code) {
  background-color: #f0f2f5;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 0.9em;
}

.markdown-content :deep(pre) {
  background-color: #282c34;
  color: #abb2bf;
  padding: 16px;
  border-radius: 6px;
  overflow-x: auto;
}

.markdown-content :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
}

.markdown-content :deep(blockquote) {
  border-left: 4px solid #409EFF;
  padding-left: 16px;
  color: #606266;
  margin: 16px 0;
}

.markdown-content :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 16px 0;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
  border: 1px solid #dcdfe6;
  padding: 8px 12px;
  text-align: left;
}

.markdown-content :deep(th) {
  background-color: #f5f7fa;
  font-weight: 600;
}
</style>