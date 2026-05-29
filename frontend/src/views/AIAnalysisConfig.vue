<template>
  <div class="ai-config-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>🤖 AI 分析配置</h2>
          <el-button @click="$router.back()">
            <el-icon><Back /></el-icon>
            返回
          </el-button>
        </div>
      </template>

      <!-- 分析范围选择 -->
      <el-radio-group v-model="analysisScope" class="scope-group">
        <el-radio value="method">仅分析当前方法</el-radio>
        <el-radio value="chain">分析整条调用链（自动逐方法分析后聚合）</el-radio>
      </el-radio-group>

      <!-- 链路分析方向选择（仅链分析模式） -->
      <template v-if="analysisScope === 'chain'">
        <div style="margin-top: 12px; padding: 10px 16px; background: #f0f5ff; border-radius: 6px">
          <span style="font-weight: 600; margin-right: 12px">🔀 链路分析方向：</span>
          <el-radio-group v-model="chainDirection" @change="onDirectionChange">
            <el-radio value="upwards">⬆️ 向上分析（影响面评估：谁调用了变更方法）</el-radio>
            <el-radio value="downwards">⬇️ 向下分析（功能风险评估：变更方法调用了谁）</el-radio>
          </el-radio-group>
        </div>
      </template>

      <el-divider />

      <!-- 当前方法信息 -->
      <h3>📋 方法信息</h3>
      <el-descriptions :column="2" border v-if="currentMethod">
        <el-descriptions-item label="类名">{{ currentMethod.class_name }}</el-descriptions-item>
        <el-descriptions-item label="方法名">{{ currentMethod.method_name }}</el-descriptions-item>
        <el-descriptions-item label="签名">{{ currentMethod.signature || currentMethod.method_name + '()' }}</el-descriptions-item>
        <el-descriptions-item label="变更类型">
          <el-tag :type="changeTypeTag(currentMethod.change_type)" size="small">
            {{ currentMethod.change_type }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>

      <!-- 📝 代码版本对比 -->
      <template v-if="methodCode">
        <el-divider />
        <div class="code-compare-section">
          <div class="code-header-bar">
            <h3>📝 代码版本对比</h3>
          </div>

          <el-collapse v-model="codeCompareActive">
            <el-collapse-item name="baseline">
              <template #title>
                <span style="font-weight: 600">{{ baseline_label }} 代码 (变更前)</span>
              </template>
              <pre class="code-block baseline-code">{{ methodCode.baseline_code || '(未获取到变更前代码)' }}</pre>
            </el-collapse-item>
            <el-collapse-item name="current">
              <template #title>
                <span style="font-weight: 600">{{ version_label }} 代码 (变更后)</span>
              </template>
              <pre class="code-block current-code">{{ methodCode.current_code || '(未获取到变更后代码)' }}</pre>
            </el-collapse-item>
          </el-collapse>
        </div>
      </template>

      <!-- 调用链方法列表（仅链路分析模式） -->
      <template v-if="analysisScope === 'chain'">
        <el-divider />
        <div class="chain-methods-header">
          <h3>🔗 调用链方法列表（共 {{ store.chainMethods.length }} 个方法）</h3>
          <el-checkbox
            :model-value="store.selectedMethods.length === store.chainMethods.length"
            :indeterminate="store.selectedMethods.length > 0 && store.selectedMethods.length < store.chainMethods.length"
            @change="store.toggleSelectAll()"
          >
            全选 / 已选 {{ store.selectedMethods.length }} 个
          </el-checkbox>
        </div>

        <div class="methods-list" v-loading="methodsLoading">
          <el-card
            v-for="(method, idx) in store.chainMethods"
            :key="`${method.class_name}.${method.method_name}`"
            class="method-card"
            :class="{ selected: isMethodSelected(method) }"
            shadow="hover"
          >
            <div class="method-header">
              <el-checkbox
                :model-value="isMethodSelected(method)"
                @change="store.toggleMethod(method.class_name, method.method_name)"
              />
              <span class="method-index">{{ idx + 1 }}️</span>
              <span class="method-name">{{ method.class_name }}.{{ method.signature || method.method_name + '()' }}</span>
              <el-tag :type="changeTypeTag(method.change_type)" size="small" style="margin-left: 8px">
                {{ method.change_type }}
              </el-tag>
              <el-tag 
                v-if="method.method_status === 'analyzed'" 
                size="small" 
                style="margin-left: 4px"
              >
                ✅ 方法分析
              </el-tag>
              <el-tag 
                v-if="method.upwards_chain_status === 'analyzed'" 
                size="small" 
                type="success"
                style="margin-left: 4px"
              >
                🔗 向上链分析
              </el-tag>
              <el-tag 
                v-if="method.downwards_chain_status === 'analyzed'" 
                size="small" 
                type="success"
                style="margin-left: 4px"
              >
                🔗 向下链分析
              </el-tag>
            </div>
            <div class="method-details" v-if="method.documentation">
              <span class="detail-label">文档:</span>
              {{ method.documentation.substring(0, 120) }}{{ method.documentation.length > 120 ? '...' : '' }}
            </div>
          </el-card>
        </div>
      </template>

      <el-divider />

      <!-- 操作栏 -->
      <div class="action-bar">
        <el-checkbox v-model="store.forceFresh">🔄 强制全新分析（忽略缓存）</el-checkbox>
        <div>
          <el-button @click="$router.back()">取消</el-button>
          <el-button
            type="primary"
            @click="startAnalysis"
            :loading="submitting"
            :disabled="analysisScope === 'chain' && store.selectedMethods.length === 0"
          >
            🚀 开始 AI 分析
          </el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Back } from '@element-plus/icons-vue'
import { useAIAnalysisStore } from '@/stores/aiAnalysis'
import { getMethodCode } from '@/api/aiAnalysis'

const route = useRoute()
const router = useRouter()
const store = useAIAnalysisStore()

const analysisScope = ref<'method' | 'chain'>('method')
const chainDirection = ref('upwards')
const submitting = ref(false)
const methodsLoading = ref(false)
const methodCode = ref<any>(null)
const codeCompareActive = ref<string[]>(['current'])

const baseline_label = computed(() => route.query.baseline as string || '基线版本')
const version_label = computed(() => route.query.version as string || '当前版本')

const currentMethod = computed(() => ({
  class_name: (route.query.class_name as string) || '',
  method_name: (route.query.method_name as string) || '',
  change_type: (route.query.change_type as string) || 'UNKNOWN',
  signature: (route.query.signature as string) || ''
}))

const changeTypeTag = (type: string) => {
  const map: Record<string, any> = {
    ADDED: 'success',
    MODIFIED: 'warning',
    DELETED: 'danger',
    UNCHANGED: 'info'
  }
  return map[type] || 'info'
}

/**
 * 切换链方向时重新加载方法列表和提示词
 */
const onDirectionChange = async () => {
  const baseline = route.query.baseline as string
  const version = route.query.version as string
  
  if (baseline && version) {
    methodsLoading.value = true
    store.analysisDirection = chainDirection.value
    try {
      await store.loadChainMethods(baseline, version, chainDirection.value)
    } finally {
      methodsLoading.value = false
    }
  }
  
  // 重新加载对应方向的默认提示词
  await store.loadDefaultPrompts(
    'chain',
    currentMethod.value.class_name,
    currentMethod.value.method_name,
    currentMethod.value.change_type,
    chainDirection.value
  )
}

const isMethodSelected = (method: any) => {
  return store.selectedMethods.some(
    m => m.class_name === method.class_name && m.method_name === method.method_name
  )
}

const startAnalysis = async () => {
  if (analysisScope.value === 'chain' && store.selectedMethods.length === 0) {
    ElMessage.warning('请至少选择一个方法进行分析')
    return
  }

  submitting.value = true
  try {
    // 链分析模式使用用户选择的方向
    if (analysisScope.value === 'chain') {
      store.analysisDirection = chainDirection.value
    }
    const result = await store.submitTask({
      analysisType: analysisScope.value,
      methodInfo: {
        class_name: currentMethod.value.class_name,
        method_name: currentMethod.value.method_name,
        change_type: currentMethod.value.change_type
      }
    })

    if (result.status === 'conflict') {
      ElMessage.warning(result.message)
      // 已有任务，仍然跳转到进度页
      router.push({
        name: 'AIAnalysisProgress',
        params: { taskId: route.params.taskId as string, aiTaskId: result.task_id }
      })
    } else {
      ElMessage.success(result.message)
      router.push({
        name: 'AIAnalysisProgress',
        params: { taskId: route.params.taskId as string, aiTaskId: result.task_id }
      })
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '创建分析任务失败')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  const baseline = route.query.baseline as string
  const version = route.query.version as string
  const direction = (route.query.direction as string) || 'upwards'
  
  // 初始化链方向
  chainDirection.value = direction
  store.analysisDirection = direction

  // 加载默认提示词模板
  await store.loadDefaultPrompts(
    'method',
    currentMethod.value.class_name,
    currentMethod.value.method_name,
    currentMethod.value.change_type,
    direction
  )

  // 加载方法代码对比
  if (baseline && version && currentMethod.value.class_name && currentMethod.value.method_name) {
    try {
      const res = await getMethodCode({
        baseline, version,
        class_name: currentMethod.value.class_name,
        method_name: currentMethod.value.method_name
      })
      methodCode.value = res.data
    } catch (err) {
      console.error('加载方法代码失败:', err)
    }
  }

  if (baseline && version) {
    methodsLoading.value = true
    try {
      await store.loadChainMethods(baseline, version, direction)
    } finally {
      methodsLoading.value = false
    }
  }
})

// 切换分析范围时重新加载对应类型的默认提示词
watch(analysisScope, async (newScope) => {
  const direction = newScope === 'chain' ? chainDirection.value : (route.query.direction as string) || 'upwards'
  await store.loadDefaultPrompts(
    newScope,
    currentMethod.value.class_name,
    currentMethod.value.method_name,
    currentMethod.value.change_type,
    direction
  )
  store.analysisDirection = direction
})
</script>

<style scoped>
.ai-config-page {
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

.scope-group {
  margin-bottom: 8px;
}

.chain-methods-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.chain-methods-header h3 {
  margin: 0;
}

.methods-list {
  max-height: 500px;
  overflow-y: auto;
}

.method-card {
  margin-bottom: 8px;
  border: 2px solid transparent;
  transition: border-color 0.2s;
}

.method-card.selected {
  border-color: #409EFF;
}

.method-header {
  display: flex;
  align-items: center;
  gap: 4px;
}

.method-index {
  background: #409EFF;
  color: #fff;
  border-radius: 50%;
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  flex-shrink: 0;
}

.method-name {
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 13px;
  font-weight: 500;
}

.method-details {
  margin-top: 8px;
  margin-left: 32px;
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
}

.detail-label {
  font-weight: 600;
  color: #606266;
}

/* 代码对比区域 */
.code-compare-section {
  margin-bottom: 8px;
}

.code-header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.code-header-bar h3 {
  margin: 0;
}

.code-block {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 6px;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre;
  max-height: 400px;
  overflow-y: auto;
  margin: 0;
}

.baseline-code {
  border-left: 3px solid #909399;
}

.current-code {
  border-left: 3px solid #E6A23C;
}

.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 8px;
}
</style>
