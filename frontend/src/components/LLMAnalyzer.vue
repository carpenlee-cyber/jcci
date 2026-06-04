<template>
  <div class="llm-analyzer">
    <el-button 
      type="primary" 
      @click="startAnalysis" 
      :loading="analyzing"
      :disabled="analyzing || globalAnalyzing"
    >
      🤖 {{ analyzing ? '分析中...' : (globalAnalyzing ? '其他分析进行中...' : 'AI 分析') }}
    </el-button>
    
    <el-checkbox v-model="forceFresh" style="margin-left: 10px" :disabled="analyzing">
      🔄 强制全新分析
    </el-checkbox>
    
    <!-- 分析状态提示 -->
    <el-alert
      v-if="analyzing"
      title="AI 分析进行中，请稍候..."
      type="warning"
      :closable="false"
      show-icon
      style="margin-top: 10px"
    />
    
    <!-- 分析结果 -->
    <div v-if="analysisResult" class="result-container">
      <el-alert
        v-if="fromCache"
        title="♻️ 从缓存读取"
        type="info"
        :closable="false"
        show-icon
        style="margin-top: 10px"
      >
        <template #default>
          <div v-if="cacheInfo">
            创建时间: {{ cacheInfo.created_at }} | 
            模型: {{ cacheInfo.model_name }} | 
            耗时: {{ cacheInfo.analysis_duration?.toFixed(2) }}s
          </div>
        </template>
      </el-alert>
      
      <el-alert
        v-else
        title="✅ 全新分析完成"
        type="success"
        :closable="false"
        show-icon
        style="margin-top: 10px"
      />
      
      <div class="markdown-content" v-html="renderedMarkdown"></div>
    </div>
    
    <!-- 错误信息 -->
    <el-alert
      v-if="error"
      :title="`❌ 分析失败: ${error}`"
      type="error"
      :closable="false"
      show-icon
      style="margin-top: 10px"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '@/api/client'
import { marked } from 'marked'

const props = defineProps<{
  analysisType: 'method' | 'chain'
  data: any
  direction?: string
  baseline?: string
  version?: string
}>()

const analyzing = ref(false)
const globalAnalyzing = ref(false)
const forceFresh = ref(false)
const analysisResult = ref('')
const fromCache = ref(false)
const cacheInfo = ref<any>(null)
const error = ref('')

const renderedMarkdown = computed(() => {
  if (!analysisResult.value) return ''
  return marked(analysisResult.value)
})

// 轮询全局 LLM 状态
let statusPollTimer: number | null = null

const checkGlobalStatus = async () => {
  try {
    const response = await apiClient.get('/analysis/llm-status')
    const status = response.data.status
    globalAnalyzing.value = status === 'analyzing'
    
    // 如果全局分析已结束，且当前组件正在分析中，自动完成
    if (status === 'idle' && analyzing.value) {
      // 分析已完成，由请求本身处理
    }
  } catch {
    // 忽略状态查询失败
  }
}

const startStatusPolling = () => {
  checkGlobalStatus()
  statusPollTimer = window.setInterval(checkGlobalStatus, 2000)
}

const stopStatusPolling = () => {
  if (statusPollTimer) {
    clearInterval(statusPollTimer)
    statusPollTimer = null
  }
}

onMounted(() => {
  startStatusPolling()
})

onUnmounted(() => {
  stopStatusPolling()
})

const startAnalysis = async () => {
  // 先检查全局状态
  try {
    const statusResp = await apiClient.get('/analysis/llm-status')
    if (statusResp.data.status === 'analyzing') {
      ElMessage.warning('已有 LLM 分析正在执行中，请等待完成后再试')
      return
    }
  } catch {
    // 状态检查失败，继续尝试
  }
  
  analyzing.value = true
  error.value = ''
  analysisResult.value = ''
  fromCache.value = false
  cacheInfo.value = null
  
  try {
    const endpoint = props.analysisType === 'method' ? '/analysis/analyze/method' : '/analysis/analyze/chain'
    
    const requestData = props.analysisType === 'method' 
      ? {
          method_info: props.data.method_info || props.data,
          db_info: props.data.db_info || {},
          direction: props.direction || 'upwards',
          force_fresh: forceFresh.value,
          baseline: props.baseline || '',
          version: props.version || ''
        }
      : {
          chain_data: props.data,
          direction: props.direction || 'upwards',
          force_fresh: forceFresh.value
        }
    
    const response = await apiClient.post(endpoint, requestData)
    
    analysisResult.value = response.data.result
    fromCache.value = response.data.from_cache
    cacheInfo.value = response.data.cache_info
    
    ElMessage.success('分析完成')
  } catch (err: any) {
    console.error('分析失败:', err)
    if (err.response?.status === 409) {
      error.value = '已有 LLM 分析正在执行中，请等待完成后再试'
      ElMessage.warning(error.value)
    } else {
      error.value = err.response?.data?.detail || err.message || '未知错误'
      ElMessage.error('分析失败')
    }
  } finally {
    analyzing.value = false
  }
}
</script>

<style scoped>
.llm-analyzer {
  margin-top: 10px;
}

.result-container {
  margin-top: 15px;
  padding: 15px;
  background-color: #f5f7fa;
  border-radius: 4px;
}

.markdown-content {
  margin-top: 10px;
  line-height: 1.6;
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3) {
  margin-top: 20px;
  margin-bottom: 10px;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  padding-left: 20px;
}

.markdown-content :deep(code) {
  background-color: #e9ecef;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: 'Courier New', monospace;
}

.markdown-content :deep(pre) {
  background-color: #282c34;
  color: #abb2bf;
  padding: 15px;
  border-radius: 5px;
  overflow-x: auto;
}
</style>
