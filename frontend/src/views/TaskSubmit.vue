<template>
  <div class="task-submit">
    <el-card>
      <template #header>
        <h2>📝 提交分析任务</h2>
        <div v-if="isReadonly" class="readonly-notice">
          <el-alert type="info" :closable="false" show-icon>
            部分字段已预填充，Git仓库地址可修改，其他字段为只读
          </el-alert>
        </div>
      </template>

      <el-form :model="form" :rules="rules" ref="formRef" label-width="120px">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="Git仓库地址" prop="git_url">
              <el-input v-model="form.git_url" placeholder="https://github.com/user/repo.git" :readonly="false" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="Git用户名" prop="username">
              <el-input v-model="form.username" placeholder="your_username" :readonly="isReadonly" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="旧版本标签" prop="tag_old">
              <el-input v-model="form.tag_old" placeholder="v1.0.0 或 commit hash" :readonly="isReadonly" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="新版本标签" prop="tag_new">
              <el-input v-model="form.tag_new" placeholder="v2.0.0 或 commit hash" :readonly="isReadonly" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="最大分析深度">
          <el-slider v-model="form.max_depth" :min="1" :max="10" show-input :disabled="isReadonly" />
        </el-form-item>

        <el-divider>埋点信息（可选）</el-divider>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="项目编号">
              <el-input v-model="form.project_code" placeholder="PROJ-001" :readonly="isReadonly" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="子任务阶段">
              <el-input v-model="form.task_stage" placeholder="Phase-1" :readonly="isReadonly" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item>
          <el-button type="primary" @click="submitTask" :loading="submitting" size="large">
            🚀 提交分析任务
          </el-button>
          <el-button v-if="isReadonly" type="warning" @click="abandonTask" :loading="abandoning" size="large" style="margin-left: 20px;">
            ❌ 放弃分析任务（此次流水线发版不再要求分析，不点下次还会收到该通知）
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { taskApi, type TaskSubmitRequest } from '@/api/task'

const CACHE_KEY = 'task_submit_form_cache'

const router = useRouter()
const route = useRoute()
const formRef = ref<FormInstance>()
const submitting = ref(false)
const abandoning = ref(false) // 放弃任务加载状态
const isReadonly = ref(false) // 是否只读模式

// 从 localStorage 加载缓存
const loadCache = (): Partial<TaskSubmitRequest> => {
  try {
    const cached = localStorage.getItem(CACHE_KEY)
    if (cached) {
      return JSON.parse(cached)
    }
  } catch {
    // 缓存数据损坏，清除
    localStorage.removeItem(CACHE_KEY)
  }
  return {}
}

// 保存缓存到 localStorage
const saveCache = (data: TaskSubmitRequest) => {
  // 不缓存 user_name 和 user_id（始终保持默认值）
  const { user_name, user_id, ...cacheData } = data
  localStorage.setItem(CACHE_KEY, JSON.stringify(cacheData))
}

// 解析URL参数
const parseUrlParams = () => {
  const query = route.query

  if (Object.keys(query).length === 0) {
    return null
  }

  // 检查是否有预填充参数
  if (query.username || query.tag_old || query.tag_new) {
    isReadonly.value = query.readonly === 'true'
    return {
      git_url: query.git_url as string || '',
      username: query.username as string || '',
      tag_old: query.tag_old as string || '',
      tag_new: query.tag_new as string || '',
      max_depth: query.max_depth ? parseInt(query.max_depth as string) : 7,
      project_code: query.project_code as string || '',
      task_stage: query.task_stage as string || ''
    }
  }

  return null
}

// 获取URL中的pipeline_analysis_id参数
const getPipelineAnalysisId = () => {
  const query = route.query
  return query.pipeline_analysis_id as string || ''
}

const cached = loadCache()
const urlParams = parseUrlParams()

const form = reactive<TaskSubmitRequest>({
  git_url: urlParams?.git_url || cached.git_url || '',
  username: urlParams?.username || cached.username || '',
  tag_old: urlParams?.tag_old || cached.tag_old || '',
  tag_new: urlParams?.tag_new || cached.tag_new || '',
  max_depth: urlParams?.max_depth || cached.max_depth || 5,
  project_code: urlParams?.project_code || cached.project_code || '',
  task_stage: urlParams?.task_stage || cached.task_stage || '',
  user_name: '网页用户',
  user_id: 'web'
})

const rules: FormRules = {
  git_url: [
    { required: true, message: '请输入 Git 仓库地址', trigger: 'blur' }
  ],
  username: [
    { required: !isReadonly.value, message: '请输入用户名', trigger: 'blur' }
  ],
  tag_old: [
    { required: !isReadonly.value, message: '请输入旧版本标签', trigger: 'blur' }
  ],
  tag_new: [
    { required: !isReadonly.value, message: '请输入新版本标签', trigger: 'blur' }
  ]
}

const submitTask = async () => {
  if (!formRef.value) return

  await formRef.value.validate(async (valid) => {
    if (!valid) return

    submitting.value = true
    try {
      const response = await taskApi.submitTask(form)
      const data = response.data
      
      // 提交成功后缓存表单数据
      saveCache({ ...form })

      // 去重处理
      if (data.duplicate) {
        if (data.result_url) {
          // 已完成，直接跳转到结果页
          ElMessage.info(data.message || '已存在相同的分析结果，正在跳转...')
          router.replace(data.result_url)
        } else {
          // 正在排队或执行中，跳转到任务列表
          ElMessage.warning(data.message || '相同的任务正在处理中')
          router.push('/tasks')
        }
        return
      }

      ElMessage.success('任务提交成功！')

      // 跳转到任务列表
      router.push('/tasks')
    } catch (error: any) {
      ElMessage.error(`提交失败: ${error.response?.data?.detail || error.message}`)
    } finally {
      submitting.value = false
    }
  })
}

const abandonTask = async () => {
  try {
    abandoning.value = true

    const pipelineAnalysisId = getPipelineAnalysisId()
    if (!pipelineAnalysisId) {
      ElMessage.error('无法获取流水线分析ID')
      return
    }

    await taskApi.abandonTask({
      pipeline_analysis_id: pipelineAnalysisId,
      username: form.username
    })

    ElMessage.success('已放弃分析任务，该流水线发版将不再要求分析')

    // 关闭页面或跳转
    setTimeout(() => {
      window.close() // 尝试关闭窗口
    }, 1000)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || '放弃任务失败')
  } finally {
    abandoning.value = false
  }
}
</script>

<style scoped>
.task-submit {
  max-width: 900px;
  margin: 0 auto;
}

.readonly-notice {
  margin-top: 10px;
}
</style>