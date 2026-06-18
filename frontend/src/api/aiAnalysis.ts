/**
 * AI 分析 API 封装
 */
import apiClient from './client'

// AI 分析任务可能耗时较长，单独设置超时
apiClient.defaults.timeout = 300000

export interface CreateTaskRequest {
  analysis_type: 'method' | 'chain'
  direction: string
  baseline: string
  version: string
  class_name: string
  method_name: string
  change_type: string
  force_fresh: boolean
  custom_system_prompt: string
  custom_analysis_prompt: string
  method_info?: any
  db_info?: any
  chain_data?: any
  selected_methods?: any[]
}

export interface TaskStatus {
  task_id: string
  analysis_type: string
  status: string
  progress: number
  total_methods: number
  completed_methods: number
  current_stage: string
  error_message: string | null
  baseline: string
  version: string
  class_name: string
  method_name: string
  change_type: string
  direction: string
  sub_tasks: Array<{
    result_id: string
    class_name: string
    method_name: string
    status: string
    from_cache: boolean
  }>
}

export interface NodeStatus {
  class_name: string
  method_name: string
  change_type: string
  method_status: 'none' | 'analyzed'
  upwards_chain_status: 'none' | 'analyzed'
  downwards_chain_status: 'none' | 'analyzed'
  running_task_id: string | null
  latest_method_result_id: string | null
  latest_upwards_chain_result_id: string | null
  latest_downwards_chain_result_id: string | null
  /** 数据库精确标识 */
  class_id?: number
  method_id?: number
}

export interface ChainMethod {
  class_name: string
  method_name: string
  signature: string
  change_type: string
  parameters: string
  return_type: string
  documentation: string
  has_cached_analysis: boolean
  cached_result_id: string | null
  method_status: string
  upwards_chain_status: string
  downwards_chain_status: string
  /** 数据库精确标识 */
  class_id?: number
  method_id?: number
}

/**
 * 创建异步分析任务
 */
export function createAnalysisTask(data: CreateTaskRequest) {
  return apiClient.post<{ task_id: string; status: string; message: string }>(
    '/analysis/tasks', data
  )
}

/**
 * 查询任务状态
 */
export function getTaskStatus(taskId: string) {
  return apiClient.get<TaskStatus>(`/analysis/tasks/${taskId}`)
}

/**
 * 获取分析结果
 */
export function getAnalysisResult(resultId: string) {
  return apiClient.get(`/analysis/results/${resultId}`)
}

/**
 * 批量查询节点分析状态
 */
export function getNodesStatus(baseline: string, version: string, nodes: any[]) {
  return apiClient.post<{ nodes: NodeStatus[] }>('/analysis/nodes-status', {
    baseline,
    version,
    nodes
  })
}

/**
 * 获取调用链方法列表
 */
export function getChainMethods(baseline: string, version: string, direction: string) {
  return apiClient.get<{ methods: ChainMethod[]; total: number }>(
    `/analysis/${baseline}/${version}/chain-methods`,
    { params: { direction } }
  )
}

/**
 * 获取默认提示词模板
 */
export function getDefaultPrompts(params: {
  analysis_type: string
  class_name?: string
  method_name?: string
  change_type?: string
  direction?: string
}) {
  return apiClient.get<{ system_prompt: string; analysis_prompt: string }>(
    '/analysis/default-prompts',
    { params }
  )
}

/**
 * 获取方法源代码（基线版本和当前版本对比）
 */
export function getMethodCode(params: {
  baseline: string
  version: string
  class_name: string
  method_name: string
  signature?: string
  class_id?: number
  method_id?: number
}) {
  return apiClient.get<{
    baseline_code: string
    current_code: string
    annotations: string
    access_modifier: string
    return_type: string
    parameters: string
    documentation: string
    class_name: string
    method_name: string
  }>('/analysis/method-code', { params })
}
