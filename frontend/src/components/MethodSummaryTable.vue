<template>
  <div class="method-summary-table">
    <div class="table-toolbar">
      <span class="table-info">
        共 <strong>{{ total }}</strong> 个变更方法
        <template v-if="selectedKey">| 已选中: <el-tag size="small" type="primary">{{ selectedKey }}</el-tag></template>
      </span>
      <el-input
        v-model="filterText"
        placeholder="搜索变动方法..."
        clearable
        :prefix-icon="Search"
        style="width: 280px"
        size="small"
      />
    </div>

    <el-table
      :data="filteredMethods"
      :default-sort="{ prop: 'change_type', order: 'ascending' }"
      size="small"
      stripe
      highlight-current-row
      @current-change="handleSelect"
      @row-click="handleSelect"
      :max-height="400"
      v-loading="loading"
    >
      <el-table-column label="变动的方法" min-width="280" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="changed-method">{{ row.class_name }}.{{ row.method_name }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="change_type" label="变更" width="90" sortable>
        <template #default="{ row }">
          <el-tag :type="getChangeTagType(row.change_type)" size="small">
            {{ row.change_type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="顶层方法" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <template v-if="row.endpoints && row.endpoints.length > 0">
            <span
              v-for="(ep, i) in row.endpoints"
              :key="i"
              class="endpoint-entry"
            >
              <template v-if="i > 0">, </template>
              <span class="endpoint-class">{{ ep.class_name }}</span>.{{ ep.method_name }}
            </span>
          </template>
          <span v-else class="no-data">—</span>
        </template>
      </el-table-column>
      <el-table-column label="API 路径" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <template v-if="row.endpoints && row.endpoints.length > 0">
            <el-tag
              v-for="(ep, i) in row.endpoints"
              :key="i"
              size="small"
              style="margin: 1px 2px"
            >
              {{ (ep.api_paths || [])[0] || '—' }}
            </el-tag>
          </template>
          <span v-else class="no-data">—</span>
        </template>
      </el-table-column>
      <el-table-column label="顶层方法说明" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <template v-if="row.endpoints && row.endpoints.length > 0">
            <span
              v-for="(ep, i) in row.endpoints"
              :key="i"
            >
              <template v-if="i > 0">; </template>
              <span
                v-if="ep.documentation && ep.documentation !== 'None'"
                class="doc-preview"
              >
                {{ ep.documentation.replace(/\n/g, ' ').substring(0, 60) }}{{ ep.documentation.length > 60 ? '…' : '' }}
              </span>
              <span v-else class="no-doc">—</span>
            </span>
          </template>
          <span v-else class="no-data">—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default>
          <el-button size="small" type="primary" text>[详情]</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && filteredMethods.length === 0" description="没有找到匹配的方法" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import type { ChainMethodSummary } from '@/api/analysis'

const props = defineProps<{
  methods: ChainMethodSummary[]
  total: number
  loading?: boolean
  selectedKey?: string
}>()

const emit = defineEmits<{
  select: [method: ChainMethodSummary]
}>()

const filterText = ref('')

const filteredMethods = computed(() => {
  if (!filterText.value) return props.methods
  const q = filterText.value.toLowerCase()
  return props.methods.filter(
    m => m.class_name.toLowerCase().includes(q) || m.method_name.toLowerCase().includes(q)
  )
})

const handleSelect = (row: ChainMethodSummary | undefined) => {
  if (row) emit('select', row)
}

const getChangeTagType = (type: string) => {
  const map: Record<string, any> = {
    ADDED: 'success',
    MODIFIED: 'warning',
    DELETED: 'danger',
    UNCHANGED: 'info'
  }
  return map[type] || 'info'
}
</script>

<style scoped>
.method-summary-table {
  padding: 4px 0;
}

.table-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.table-info {
  font-size: 13px;
  color: #606266;
}

.table-info strong {
  color: #409EFF;
}

.changed-method {
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 13px;
}

.endpoint-entry {
  display: inline;
}

.endpoint-class {
  color: #909399;
  font-size: 12px;
}

.doc-preview {
  color: #909399;
  font-size: 12px;
}

.no-doc {
  color: #C0C4CC;
  font-size: 12px;
}

.no-data {
  color: #C0C4CC;
  font-size: 12px;
}
</style>
