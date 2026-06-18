/**
 * AI 分析状态管理 (Pinia Store)
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  createAnalysisTask,
  getTaskStatus,
  getAnalysisResult,
  getNodesStatus,
  getChainMethods,
  getDefaultPrompts,
  type CreateTaskRequest,
  type TaskStatus,
  type NodeStatus,
  type ChainMethod
} from '@/api/aiAnalysis'

export const useAIAnalysisStore = defineStore('aiAnalysis', () => {
  // ========== 分析配置 ==========
  const selectedBaseline = ref('')
  const selectedVersion = ref('')
  const analysisDirection = ref('upwards')
  const forceFresh = ref(false)
  const customSystemPrompt = ref('')
  const customAnalysisPrompt = ref('')
  const selectedMethods = ref<any[]>([])
  const chainMethods = ref<ChainMethod[]>([])

  // ========== 任务状态 ==========
  const currentTaskId = ref('')
  const taskStatus = ref<TaskStatus | null>(null)
  const isPolling = ref(false)
  let pollTimer: number | null = null

  // ========== 节点状态 ==========
  const nodesStatusMap = ref<Map<string, NodeStatus>>(new Map())
  const nodeStatusLoading = ref(false)

  // ========== 分析结果 ==========
  const currentResult = ref<any>(null)

  /**
   * 加载调用链方法列表
   */
  async function loadChainMethods(baseline: string, version: string, direction: string) {
    try {
      const response = await getChainMethods(baseline, version, direction)
      chainMethods.value = response.data.methods
      // 默认全选
      selectedMethods.value = [...response.data.methods]
      selectedBaseline.value = baseline
      selectedVersion.value = version
      analysisDirection.value = direction
    } catch (err) {
      console.error('加载方法列表失败:', err)
      chainMethods.value = []
    }
  }

  /**
   * 加载默认提示词模板
   */
  async function loadDefaultPrompts(analysisType: string, className: string, methodName: string, changeType: string, direction: string) {
    try {
      const response = await getDefaultPrompts({
        analysis_type: analysisType,
        class_name: className,
        method_name: methodName,
        change_type: changeType,
        direction
      })
      customSystemPrompt.value = response.data.system_prompt
      customAnalysisPrompt.value = response.data.analysis_prompt
    } catch (err) {
      console.error('加载默认提示词失败:', err)
    }
  }

  /**
   * 切换方法勾选
   */
  function toggleMethod(method: ChainMethod | any) {
    // 优先使用数据库ID精确匹配
    if (method.class_id !== undefined && method.method_id !== undefined) {
      const idx = selectedMethods.value.findIndex(
        m => m.class_id === method.class_id && m.method_id === method.method_id
      )
      if (idx >= 0) {
        selectedMethods.value.splice(idx, 1)
      } else {
        const found = chainMethods.value.find(
          m => m.class_id === method.class_id && m.method_id === method.method_id
        )
        if (found) {
          selectedMethods.value.push(found)
        }
      }
      return
    }
    // 回退到文本匹配
    const key = `${method.class_name}.${method.method_name}`
    const idx = selectedMethods.value.findIndex(
      m => `${m.class_name}.${m.method_name}` === key
    )
    if (idx >= 0) {
      selectedMethods.value.splice(idx, 1)
    } else {
      const found = chainMethods.value.find(
        m => m.class_name === method.class_name && m.method_name === method.method_name
      )
      if (found) {
        selectedMethods.value.push(found)
      }
    }
  }

  /**
   * 全选/取消全选
   */
  function toggleSelectAll() {
    if (selectedMethods.value.length === chainMethods.value.length) {
      selectedMethods.value = []
    } else {
      selectedMethods.value = [...chainMethods.value]
    }
  }

  /**
   * 创建并提交分析任务
   */
  async function submitTask(data: {
    analysisType: 'method' | 'chain'
    methodInfo?: any
    dbInfo?: any
    chainData?: any
  }) {
    const request: CreateTaskRequest = {
      analysis_type: data.analysisType,
      direction: analysisDirection.value,
      baseline: selectedBaseline.value,
      version: selectedVersion.value,
      class_name: data.methodInfo?.class_name || '',
      method_name: data.methodInfo?.method_name || '',
      change_type: data.methodInfo?.change_type || 'UNKNOWN',
      force_fresh: forceFresh.value,
      custom_system_prompt: customSystemPrompt.value,
      custom_analysis_prompt: customAnalysisPrompt.value,
      method_info: data.methodInfo,
      db_info: data.dbInfo,
      chain_data: data.chainData || (data.analysisType === 'chain' ? {
        method_info: {
          ...data.methodInfo,
          class_id: data.methodInfo?.class_id,
          method_id: data.methodInfo?.method_id
        },
        methods: selectedMethods.value.map(m => ({
          class_name: m.class_name,
          method_name: m.method_name,
          signature: m.signature || `${m.method_name}()`,
          change_type: m.change_type || 'UNKNOWN',
          documentation: m.documentation || '',
          class_id: m.class_id,
          method_id: m.method_id
        }))
      } : undefined),
      selected_methods: data.analysisType === 'chain' ? selectedMethods.value : undefined
    }

    const response = await createAnalysisTask(request)
    currentTaskId.value = response.data.task_id
    return response.data
  }

  /**
   * 开始轮询任务状态
   */
  function startPolling(onComplete?: () => void) {
    if (isPolling.value) return
    isPolling.value = true

    const poll = async () => {
      if (!currentTaskId.value || !isPolling.value) {
        stopPolling()
        return
      }

      try {
        const response = await getTaskStatus(currentTaskId.value)
        taskStatus.value = response.data

        if (response.data.status === 'completed' || response.data.status === 'failed') {
          stopPolling()
          if (onComplete) onComplete()
        }
      } catch (err) {
        console.error('查询任务状态失败:', err)
      }
    }

    poll() // 立即执行一次
    pollTimer = window.setInterval(poll, 2000)
  }

  /**
   * 停止轮询
   */
  function stopPolling() {
    isPolling.value = false
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  /**
   * 加载分析结果
   */
  async function loadResult(resultId: string) {
    try {
      const response = await getAnalysisResult(resultId)
      currentResult.value = response.data
      return response.data
    } catch (err) {
      console.error('加载分析结果失败:', err)
      return null
    }
  }

  /**
   * 批量加载节点分析状态
   */
  async function loadNodesStatus(baseline: string, version: string, nodes: any[]) {
    nodeStatusLoading.value = true
    try {
      const response = await getNodesStatus(baseline, version, nodes)
      // 增量更新：只更新本次查询返回的节点，不覆盖未出现的已有节点
      // 防止不同树实例或定时刷新导致已分析状态丢失
      if (!nodesStatusMap.value) {
        nodesStatusMap.value = new Map()
      }
      for (const node of response.data.nodes) {
        const key = `${node.class_name}.${node.method_name}`
        nodesStatusMap.value.set(key, node)
      }
    } catch (err) {
      console.error('加载节点状态失败:', err)
    } finally {
      nodeStatusLoading.value = false
    }
  }

  /**
   * 获取单个节点状态
   */
  function getNodeStatus(class_name: string, method_name: string): NodeStatus | undefined {
    return nodesStatusMap.value.get(`${class_name}.${method_name}`)
  }

  /**
   * 重置状态
   */
  function reset() {
    currentTaskId.value = ''
    taskStatus.value = null
    stopPolling()
  }

  return {
    // 配置
    selectedBaseline,
    selectedVersion,
    analysisDirection,
    forceFresh,
    customSystemPrompt,
    customAnalysisPrompt,
    selectedMethods,
    chainMethods,
    // 任务
    currentTaskId,
    taskStatus,
    isPolling,
    // 节点
    nodesStatusMap,
    nodeStatusLoading,
    // 结果
    currentResult,
    // 方法
    loadChainMethods,
    loadDefaultPrompts,
    toggleMethod,
    toggleSelectAll,
    submitTask,
    startPolling,
    stopPolling,
    loadResult,
    loadNodesStatus,
    getNodeStatus,
    reset
  }
})
