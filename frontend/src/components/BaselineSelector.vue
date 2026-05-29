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
import { ref, computed, onMounted, watch } from 'vue'
import { getBaselines } from '@/api/analysis'
import type { BaselineInfo } from '@/api/analysis'

const props = defineProps<{
  initialBaseline?: string
  initialVersion?: string
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

// 格式化基线名称（替换下划线为空格）
const formatBaselineName = (name: string) => {
  return name.replace(/_/g, ' ')
}

// 格式化版本名称
const formatVersionName = (name: string) => {
  return name.replace(/_/g, ' ')
}

// 加载基线列表
const loadBaselines = async () => {
  loadingBaselines.value = true
  try {
    const response = await getBaselines()
    baselines.value = response.data
    
    // 如果有初始基线，尝试选中它
    if (props.initialBaseline) {
      const found = baselines.value.find(b => b.name === props.initialBaseline)
      if (found) {
        selectedBaseline.value = props.initialBaseline
        // 如果有初始版本且在版本列表中
        if (props.initialVersion && found.versions.includes(props.initialVersion)) {
          selectedVersion.value = props.initialVersion
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
