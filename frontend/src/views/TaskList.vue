<template>
  <div class="task-list">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>📋 任务列表</h2>
          <div class="header-actions">
            <el-switch
              v-model="autoRefresh"
              active-text="自动刷新"
              @change="toggleAutoRefresh"
              style="margin-right: 15px"
            />
            <el-button @click="loadTasks" :loading="loading">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
            <el-button type="primary" @click="$router.push('/submit')">
              <el-icon><Plus /></el-icon>
              提交新任务
            </el-button>
          </div>
        </div>
      </template>

      <!-- 统计卡片 -->
      <el-row :gutter="16" class="stats-row" v-if="stats.total > 0">
        <el-col :span="4">
          <el-statistic title="总任务数" :value="stats.total" />
        </el-col>
        <el-col :span="5">
          <el-statistic title="已完成" :value="stats.completed">
            <template #suffix>
              <el-tag type="success" size="small">{{ getPercentage(stats.completed, stats.total) }}%</el-tag>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="5">
          <el-statistic title="运行中" :value="stats.running">
            <template #suffix>
              <el-tag type="warning" size="small">{{ getPercentage(stats.running, stats.total) }}%</el-tag>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="5">
          <el-statistic title="等待中" :value="stats.pending">
            <template #suffix>
              <el-tag type="info" size="small">{{ getPercentage(stats.pending, stats.total) }}%</el-tag>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="5">
          <el-statistic title="失败" :value="stats.failed">
            <template #suffix>
              <el-tag type="danger" size="small">{{ getPercentage(stats.failed, stats.total) }}%</el-tag>
            </template>
          </el-statistic>
        </el-col>
      </el-row>

      <el-divider v-if="stats.total > 0" />

      <el-table :data="tasks" style="width: 100%" v-loading="loading">
        <el-table-column label="项目-版本-阶段" width="220">
          <template #default="{ row }">
            <span class="project-stage">
              <span class="project-code">{{ row.project_code || '-' }}</span>
              <span class="stage-sep">_</span>
              <span class="task-stage">{{ row.task_stage || '-' }}</span>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="task_id" label="任务ID" width="150" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="git_url" label="Git仓库" min-width="200" show-overflow-tooltip />
        <el-table-column prop="tag_old" label="基线版本" width="150" />
        <el-table-column prop="tag_new" label="目标版本" width="150" />
        <el-table-column prop="progress" label="进度" width="120">
          <template #default="{ row }">
            <el-progress :percentage="row.progress" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button 
              size="small" 
              type="primary"
              @click="viewAnalysis(row.task_id)"
              :disabled="row.status !== 'completed'"
            >
              查看结果
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      
      <div class="pagination" v-if="total > 0">
        <el-pagination
          layout="total, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          @current-change="handlePageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { taskApi } from '@/api/task'

const router = useRouter()
const tasks = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const pageSize = 20
const currentPage = ref(1)
const autoRefresh = ref(true)
let refreshInterval: number | null = null

const stats = reactive({
  total: 0,
  completed: 0,
  running: 0,
  pending: 0,
  failed: 0
})

const getPercentage = (value: number, total: number) => {
  if (total === 0) return 0
  return Math.round((value / total) * 100)
}

const getStatusType = (status: string) => {
  const typeMap: Record<string, any> = {
    pending: 'info',
    running: 'warning',
    completed: 'success',
    failed: 'danger'
  }
  return typeMap[status] || 'info'
}

const loadTasks = async () => {
  loading.value = true
  try {
    const response = await taskApi.listTasks(pageSize, (currentPage.value - 1) * pageSize)
    tasks.value = response.data.tasks
    total.value = response.data.total
    updateStats(response.data.tasks)
  } catch (error) {
    ElMessage.error('加载任务列表失败')
  } finally {
    loading.value = false
  }
}

const updateStats = (taskList: any[]) => {
  stats.total = taskList.length
  stats.completed = taskList.filter(t => t.status === 'completed').length
  stats.running = taskList.filter(t => t.status === 'running').length
  stats.pending = taskList.filter(t => t.status === 'pending').length
  stats.failed = taskList.filter(t => t.status === 'failed').length
}

const toggleAutoRefresh = (enabled: boolean) => {
  if (enabled) {
    refreshInterval = window.setInterval(() => {
      loadTasks()
    }, 5000)
  } else {
    if (refreshInterval) {
      clearInterval(refreshInterval)
      refreshInterval = null
    }
  }
}

const handlePageChange = (page: number) => {
  currentPage.value = page
  loadTasks()
}

const viewAnalysis = (taskId: string) => {
  const task = tasks.value.find((t: any) => t.task_id === taskId)
  const baseline = task?.tag_old || ''
  const version = task?.tag_new || ''
  const query = `?baseline=${encodeURIComponent(baseline)}&version=${encodeURIComponent(version)}`
  router.push(`/analysis/${taskId}${query}`)
}

onMounted(() => {
  loadTasks()
  toggleAutoRefresh(true)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
    refreshInterval = null
  }
})
</script>

<style scoped>
.task-list {
  max-width: 1400px;
  margin: 0 auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  align-items: center;
}

.card-header h2 {
  margin: 0;
}

.stats-row {
  margin-bottom: 10px;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}
</style>
