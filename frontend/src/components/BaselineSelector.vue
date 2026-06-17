<template>
  <div class="baseline-selector">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>📁 选择分析结果</span>
        </div>
      </template>
      
      <el-form label-width="80px">
        <el-form-item label="基线版本">
          <el-select
            v-model="selectedBaseline"
            placeholder="请选择基线"
            style="width: 100%"
            @change="handleBaselineChange"
            :loading="loadingBaselines"
            :disabled="props.lockedBaseline"
          >
            <el-option
              v-for="baseline in baselines"
              :key="baseline.name"
              :label="formatBaselineName(baseline.name)"
              :value="baseline.name"
            />
          </el-select>
        </el-form-item>
        
        <el-form-item label="目标版本" v-if="selectedBaseline">
          <el-select
            v-model="selectedVersion"
            placeholder="请选择版本"
            style="width: 100%"
            @change="handleVersionChange"
            :loading="loadingVersions"
            :disabled="!selectedBaseline"
          >
            <el-option
              v-for="version in currentVersions"
              :key="version"
              :label="formatVersionName(version)"
              :value="version"
            />
          </el-select>
        </el-form-item>
      </el-form>
      
      <el-alert
        v-if="selectedBaseline && selectedVersion"
        :title="`已选择: ${selectedBaseline} → ${selectedVersion}`"
        type="success"
        :closable="false"
        show-icon
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getBaselines } from '@/api/analysis'
import type { BaselineInfo } from '@/api/analysis'

const props = defineProps<{
  initialBaseline?: string
  initialVersion?: string
  lockedBaseline?: boolean
}>()

const emit = defineEmits<{
  (e: 'change', baseline: string, version: string): void
}>()

const loadingBaselines = ref(false)
const loadingVersions = ref(false)
const baselines = ref<BaselineInfo[]>([])
const selectedBaseline = ref(props.initialBaseline || '')
const selectedVersion = ref(props.initialVersion || '')

const currentVersions = computed(() => {
  const baseline = baselines.value.find(b => b.name === selectedBaseline.value)
  return baseline ? baseline.versions : []
})

// ── 提取短标签（与 Python extract_short_tag 对齐：内嵌标识符优先） ──
const extractShortTag = (tag: string): string => {
  if (!tag) return ''
  // 优先提取内嵌的短标识符（如 20260525_03 等格式）
  const innerMatch = tag.match(/[0-9]{8}_[0-9A-Z]{2,3}(?:_\d{2})?$/i)
  if (innerMatch) {
    return innerMatch[0]
  }
  // 若为完整 SHA256 + 日期后缀，截取前4+后11
  const shaMatch = tag.match(/^([0-9a-f]{4})[0-9a-f]{56}(_\d{8}_\d{2})$/i)
  if (shaMatch) {
    return shaMatch[1] + shaMatch[2]
  }
  return tag
}

// 格式化基线名称（直接返回原始名称）
const formatBaselineName = (name: string) => {
  return name
}

// 格式化版本名称（直接返回原始名称）
const formatVersionName = (name: string) => {
  return name
}

// 加载基线列表
const loadBaselines = async () => {
  loadingBaselines.value = true
  try {
    const response = await getBaselines()
    baselines.value = response.data

    // 如果有初始基线，尝试选中它
    if (props.initialBaseline) {
      // 策略1: 直接完整标签匹配
      let found = baselines.value.find(b => b.name === props.initialBaseline)
      if (!found) {
        // 策略2: 短标签回退匹配（initialBaseline 可能是短标签或带前缀的变体）
        const initShort = extractShortTag(props.initialBaseline!)
        found = baselines.value.find(b => {
          const bShort = extractShortTag(b.name)
          // 检查任一方向的包含关系
          return bShort === initShort || b.name.includes(initShort) || initShort.includes(bShort)
        })
      }
      if (found) {
        selectedBaseline.value = found.name
        // 如果有初始版本且在版本列表中，直接匹配
        if (props.initialVersion) {
          const verFound = found.versions.find(v => v === props.initialVersion)
          if (verFound) {
            selectedVersion.value = props.initialVersion
          } else {
            // 版本也可能需要短标签回退
            const initVerShort = extractShortTag(props.initialVersion)
            const verByShort = found.versions.find(v => extractShortTag(v) === initVerShort)
            selectedVersion.value = verByShort || found.versions[0]
          }
        } else if (found.versions.length > 0) {
          selectedVersion.value = found.versions[0]
        }
        // 触发变更事件
        emit('change', selectedBaseline.value, selectedVersion.value)
        return
      }
    }

    // 如果没有初始值或初始值无效，自动选择第一个
    if (baselines.value.length > 0 && !selectedBaseline.value) {
      selectedBaseline.value = baselines.value[0].name
    }
  } catch (error) {
    console.error('加载基线列表失败:', error)
  } finally {
    loadingBaselines.value = false
  }
}

// 基线变化处理
const handleBaselineChange = () => {
  selectedVersion.value = ''
  
  // 自动选择第一个版本
  if (currentVersions.value.length > 0) {
    selectedVersion.value = currentVersions.value[0]
    emit('change', selectedBaseline.value, selectedVersion.value)
  }
}

// 版本变化处理
const handleVersionChange = () => {
  if (selectedBaseline.value && selectedVersion.value) {
    emit('change', selectedBaseline.value, selectedVersion.value)
  }
}

onMounted(() => {
  loadBaselines()
})
</script>

<style scoped>
.baseline-selector {
  margin-bottom: 20px;
}

.card-header {
  font-weight: bold;
  font-size: 16px;
}
</style>