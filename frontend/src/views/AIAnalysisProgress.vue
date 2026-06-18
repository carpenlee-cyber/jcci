<template>
  <div class="ai-progress-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>⏳ 分析进度</h2>
          <el-button @click="$router.back()" :disabled="store.taskStatus?.status === 'running'">
            <el-icon><Close /></el-icon>
            关闭
          </el-button>
        </div>
      </template>

      <!-- 任务信息 -->
      <el-descriptions :column="2" border v-if="store.taskStatus">
        <el-descriptions-item label="任务类型">
          {{ store.taskStatus.analysis_type === 'chain' ? '链路分析' : '方法分析' }}
        </el-descriptions-item>
        <el-descriptions-item label="任务状态">
          <el-tag :type="statusTagType(store.taskStatus.status)">
            {{ statusLabel(store.taskStatus.status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="当前分析方法" v-if="store.taskStatus.current_stage && store.taskStatus.current_stage === 'method_analysis'">
          {{ methodSignature(store.taskStatus) }}
        </el-descriptions-item>
        <el-descriptions-item label="当前阶段" v-else-if="store.taskStatus.current_stage">
          {{ stageLabel(store.taskStatus.current_stage) }}
        </el-descriptions-item>
      </el-descriptions>

      <el-divider />

      <!-- 整体进度 -->
      <div class="overall-progress">
        <span class="progress-label">整体进度</span>
        <el-progress
          :percentage="Math.round((store.taskStatus?.progress || 0) * 100)"
          :status="progressStatus"
          :stroke-width="20"
        />
        <span class="progress-text" v-if="store.taskStatus?.analysis_type === 'chain'">
          {{ store.taskStatus?.completed_methods || 0 }} / {{ store.taskStatus?.total_methods || 0 }} 个方法
        </span>
      </div>

      <el-divider />

      <!-- 子任务列表（链路分析） -->
      <template v-if="store.taskStatus?.sub_tasks && store.taskStatus.sub_tasks.length > 0">
        <h3>方法分析详情</h3>
        <div class="sub-tasks">
          <div
            v-for="(sub, idx) in store.taskStatus.sub_tasks"
            :key="sub.result_id || idx"
            class="sub-task-item"
          >
            <span class="sub-status">
              ✅
            </span>
            <span class="sub-method">{{ sub.class_name }}.{{ sub.method_name }}</span>
            <el-tag v-if="sub.from_cache" type="info" size="small">♻️ 缓存</el-tag>
          </div>
        </div>
        <el-divider />
      </template>

      <!-- 等待中提示 -->
      <el-alert
        v-if="!store.taskStatus || store.taskStatus.status === 'pending'"
        title="任务已提交，等待执行..."
        type="info"
        :closable="false"
        show-icon
      />

      <!-- 进行中 -->
      <el-alert
        v-if="store.taskStatus?.status === 'running'"
        :title="store.taskStatus.current_stage === 'aggregation' ? '正在进行聚合分析...' : 'AI 分析进行中，请稍候...'"
        type="warning"
        :closable="false"
        show-icon
      />

      <!-- 错误 -->
      <el-alert
        v-if="store.taskStatus?.status === 'failed'"
        :title="`分析失败: ${store.taskStatus.error_message}`"
        type="error"
        :closable="false"
        show-icon
      >
        <template #default>
          <el-button type="primary" size="small" @click="retryAnalysis" style="margin-top: 8px">
            重新分析
          </el-button>
        </template>
      </el-alert>

      <!-- 完成 -->
      <el-alert
        v-if="store.taskStatus?.status === 'completed'"
        title="✅ 分析完成！"
        type="success"
        :closable="false"
        show-icon
      >
        <template #default>
          <el-button
            type="primary"
            @click="viewResult"
            style="margin-top: 8px"
            v-if="latestResultId"
          >
            📋 查看结果
          </el-button>
        </template>
      </el-alert>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Close } from '@element-plus/icons-vue'
import { useAIAnalysisStore } from '@/stores/analysisStore'

const route = useRoute()
const router = useRouter()
const store = useAIAnalysisStore()

const aiTaskId = route.params.aiTaskId as string

const latestResultId = computed(() => {
  const subs = store.taskStatus?.sub_tasks || []
  if (subs.length > 0) {
    // 链路分析：取最后一个子结果或父任务结果
    return subs[subs.length - 1].result_id
  }
  return null
})

const progressStatus = computed(() => {
  if (!store.taskStatus) return undefined
  if (store.taskStatus.status === 'failed') return 'exception'
  if (store.taskStatus.status === 'completed') return 'success'
  return undefined
})

const statusTagType = (s: string) => {
  const m: Record<string, any> = {
    pending: 'info',
    running: 'warning',
    completed: 'success',
    failed: 'danger'
  }
  return m[s] || 'info'
}

const statusLabel = (s: string) => {
  const m: Record<string, string> = {
    pending: '等待中',
    running: '分析中',
    completed: '已完成',
    failed: '失败'
  }
  return m[s] || s
}

const stageLabel = (s: string) => {
  const m: Record<string, string> = {
    method_analysis: '方法分析',
    aggregation: '聚合分析'
  }
  return m[s] || s
}

const methodSignature = (taskStatus: any) => {
  if (taskStatus.class_name && taskStatus.method_name) {
    return `${taskStatus.class_name}.${taskStatus.method_name}()`
  }
  return '未知方法'
}

const viewResult = () => {
  if (latestResultId.value) {
    router.push({
      name: 'AIAnalysisResult',
      params: {
        taskId: route.params.taskId as string,
        resultId: latestResultId.value
      },
      query: {
        aiTaskId: aiTaskId,
        class_name: store.taskStatus?.class_name || '',
        method_name: store.taskStatus?.method_name || '',
        baseline: store.taskStatus?.baseline || '',
        version: store.taskStatus?.version || ''
      }
    })
  }
}

const retryAnalysis = () => {
  router.back()
}

onMounted(() => {
  store.currentTaskId = aiTaskId
  store.startPolling(() => {
    // 完成后自动跳转结果页，携带方法信息供 AIAnalysisResult 加载
    if (latestResultId.value) {
      const ts = store.taskStatus
      setTimeout(() => {
        router.push({
          name: 'AIAnalysisResult',
          params: {
            taskId: route.params.taskId as string,
            resultId: latestResultId.value
          },
          query: {
            aiTaskId: aiTaskId,
            class_name: ts?.class_name || '',
            method_name: ts?.method_name || '',
            baseline: ts?.baseline || '',
            version: ts?.version || ''
          }
        })
      }, 1000)
    }
  })
})

onUnmounted(() => {
  // 不停止轮询，允许后台继续
  // store.stopPolling()
})
</script>

<style scoped>
.ai-progress-page {
  max-width: 800px;
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

.overall-progress {
  text-align: center;
  padding: 20px 0;
}

.progress-label {
  display: block;
  font-size: 14px;
  color: #606266;
  margin-bottom: 12px;
}

.progress-text {
  display: block;
  margin-top: 8px;
  font-size: 13px;
  color: #909399;
}

.sub-tasks {
  max-height: 400px;
  overflow-y: auto;
}

.sub-task-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid #f0f0f0;
  font-size: 13px;
}

.sub-status {
  flex-shrink: 0;
}

.sub-method {
  font-family: 'Consolas', 'Courier New', monospace;
  flex: 1;
}
</style>