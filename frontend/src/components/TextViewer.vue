<template>
  <div class="text-viewer" v-loading="loading">
    <!-- 方向切换 -->
    <el-radio-group v-model="direction" style="margin-bottom: 15px">
      <el-radio-button value="upwards">⬆️ 向上调用链</el-radio-button>
      <el-radio-button value="downwards">⬇️ 向下调用链</el-radio-button>
    </el-radio-group>

    <!-- 工具栏 -->
    <div class="toolbar" v-if="currentContent">
      <el-input
        v-model="searchText"
        placeholder="搜索..."
        clearable
        prefix-icon="Search"
        style="width: 300px; margin-right: 10px"
        @input="updateHighlight"
      />
      <el-button @click="copyContent" size="small">
        📋 复制
      </el-button>
      <span class="line-count">
        {{ currentContent.split('\n').length }} 行 | {{ currentContent.length }} 字符
      </span>
    </div>

    <!-- 内容区域 -->
    <div class="content-area" v-if="currentContent">
      <pre v-html="highlightedContent"></pre>
    </div>
    <el-empty v-else description="暂无内容" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps<{
  content?: string
  upwardsContent?: string
  downwardsContent?: string
  loading?: boolean
}>()

const direction = ref('upwards')
const searchText = ref('')
const highlightedContent = ref('')

const currentContent = computed(() => {
  if (direction.value === 'upwards') {
    return props.upwardsContent || ''
  }
  return props.downwardsContent || ''
})

const updateHighlight = () => {
  const content = currentContent.value
  if (!content) {
    highlightedContent.value = ''
    return
  }

  // 转义 HTML
  let escaped = content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // 高亮搜索词
  if (searchText.value) {
    const regex = new RegExp(`(${escapeRegex(searchText.value)})`, 'gi')
    escaped = escaped.replace(regex, '<mark style="background-color: #ffeb3b; padding: 1px 0;">$1</mark>')
  }

  // Java 关键字高亮
  const javaKeywords = [
    'public', 'private', 'protected', 'class', 'interface', 'extends', 'implements',
    'static', 'final', 'void', 'return', 'new', 'this', 'super', 'import', 'package',
    'throws', 'throw', 'try', 'catch', 'finally', 'if', 'else', 'for', 'while', 'do',
    'switch', 'case', 'default', 'break', 'continue', 'synchronized', 'volatile',
    'transient', 'native', 'abstract', 'enum', 'instanceof'
  ]

  const keywordPattern = new RegExp(`\\b(${javaKeywords.join('|')})\\b`, 'gi')
  escaped = escaped.replace(keywordPattern, '<span style="color: #d73a49; font-weight: bold;">$1</span>')

  // 方法高亮（后面跟括号）
  escaped = escaped.replace(/(\w+)(\()/g, '<span style="color: #6f42c1;">$1</span>$2')

  highlightedContent.value = escaped
}

const escapeRegex = (str: string) => {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

const copyContent = async () => {
  try {
    await navigator.clipboard.writeText(currentContent.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败')
  }
}

// 监听内容变化
watch(() => [currentContent.value, searchText.value], () => {
  updateHighlight()
}, { immediate: true })
</script>

<style scoped>
.text-viewer {
  padding: 10px;
  min-height: 300px;
}

.toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
  gap: 10px;
}

.line-count {
  color: #909399;
  font-size: 12px;
  margin-left: auto;
}

.content-area {
  background-color: #f5f7fa;
  border-radius: 4px;
  overflow: hidden;
}

.content-area pre {
  padding: 15px;
  margin: 0;
  overflow-x: auto;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-family: 'Courier New', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: #24292e;
  max-height: 600px;
  overflow-y: auto;
}
</style>
