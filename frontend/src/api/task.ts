import axios from 'axios'

const apiClient = axios.create({
  baseURL: 'http://127.0.0.1:8000/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

export interface TaskSubmitRequest {
  git_url: string
  username: string
  tag_old: string
  tag_new: string
  max_depth?: number
  password?: string
  project_code?: string
  task_stage?: string
  user_ip?: string
  user_name?: string
  user_id?: string
}

export interface TaskResponse {
  task_id: string
  status: string
  message: string
  queue_position?: number
  estimated_wait_minutes?: number
  duplicate?: boolean
  result_url?: string
}

export interface TaskStatus {
  task_id: string
  status: string
  git_url: string
  username?: string
  tag_old: string
  tag_new: string
  max_depth: number
  progress: number
  result_url?: string
  error_message?: string
  created_at: string
  started_at?: string
  completed_at?: string
  project_code?: string
  task_stage?: string
  user_ip?: string
  user_name?: string
  user_id?: string
}

export interface TaskListResponse {
  total: number
  tasks: TaskStatus[]
}

export const taskApi = {
  submitTask(data: TaskSubmitRequest) {
    return apiClient.post<TaskResponse>('/tasks/submit', data)
  },

  getTask(taskId: string) {
    return apiClient.get<TaskStatus>(`/tasks/${taskId}`)
  },

  listTasks(limit = 20, offset = 0) {
    return apiClient.get<TaskListResponse>('/tasks/', {
      params: { limit, offset }
    })
  },

  cancelTask(taskId: string) {
    return apiClient.delete(`/tasks/${taskId}`)
  },

  analyzeWithLLM(taskId: string) {
    return apiClient.post(`/tasks/_llm/analyze/${taskId}`)
  },

  getTrackingStats() {
    return apiClient.get('/stats/tracking')
  }
}
