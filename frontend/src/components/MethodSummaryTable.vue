<template>
  <div class="method-summary-table">
    <div class="table-toolbar">
      <span class="table-info">
        已加载 <strong>{{ loadedCount }}</strong> / <strong>{{ total }}</strong> 个变更方法
        <template v-if="selectedKey">| 已选中: <el-tag size="small" type="primary">{{ selectedKey }}</el-tag></template>
        <template v-if="loadingMore">
          <el-icon class="is-loading" style="margin-left: 8px"><Loading /></el-icon> 加载中...
        </template>
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
      :data="pagedMethods"
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
      <el-table-column :label="isDownwards ? '底层方法' : '顶层方法'" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <template v-if="row.endpoints && row.endpoints.length > 0">
            <span
              v-for="(ep, i) in row.endpoints"
              :key="i"
              class="endpoint-entry"
            >
              <template v-if="i > 0">, </template>
              <template v-if="ep.dao_method_signature">
                <span class="endpoint-class">{{ ep.class_name }}</span>.{{ ep.dao_method_signature }}
              </template>
              <template v-else>
                <span class="endpoint-class">{{ ep.class_name }}</span>.{{ ep.method_name }}
              </template>
            </span>
          </template>
          <span v-else class="no-data">—</span>
        </template>
      </el-table-column>
      <el-table-column :label="isDownwards ? 'SQL 内容' : 'API 路径'" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <template v-if="row.endpoints && row.endpoints.length > 0">
            <el-tag
              v-for="(ep, i) in row.endpoints"
              :key="i"
              size="small"
              style="margin: 1px 2px"
            >
              {{ ep.dao_sql_content || (ep.api_paths || [])[0] || '—' }}
            </el-tag>
          </template>
          <span v-else class="no-data">—</span>
        </template>
      </el-table-column>
      <el-table-column :label="isDownwards ? 'Mapper 方法' : '顶层方法说明'" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <template v-if="row.endpoints && row.endpoints.length > 0">
            <span
              v-for="(ep, i) in row.endpoints"
              :key="i"
            >
              <template v-if="i > 0">; </template>
              <template v-if="ep.dao_mapper_method">
                <span class="doc-preview">{{ ep.dao_mapper_method }}</span>
              </template>
              <template v-else-if="ep.documentation && ep.documentation !== 'None'">
                <span class="doc-preview">
                  {{ ep.documentation.replace(/\n/g, ' ').substring(0, 60) }}{{ ep.documentation.length > 60 ? '…' : '' }}
                </span>
              </template>
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

    <!-- 分页 -->
    <div class="table-pagination" v-if="total > 0">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="total"
        :pager-count="5"
        layout="total, prev, pager, next"
        small
        @current-change="handlePageChange"
      />
    </div>

    <el-empty v-if="!loading && pagedMethods.length === 0" description="没有找到匹配的方法" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search, Loading } from '@element-plus/icons-vue'
import type { ChainMethodSummary } from '@/api/analysis'

const props = defineProps<{
  methods: ChainMethodSummary[]
  total: number
  loading?: boolean
  loadingMore?: boolean
  selectedKey?: string
  direction?: 'upwards' | 'downwards'
}>()

const BATCH_SIZE = 100  // 每次从 API 加载 100 条
const pageSize = 20      // 每页显示 20 条

const emit = defineEmits<{
  select: [method: ChainMethodSummary]
  loadMore: [offset: number, limit: number]
}>()

const isDownwards = computed(() => props.direction === 'downwards')

const filterText = ref('')
const currentPage = ref(1)

// 已加载到前端缓冲区的方法总数
const loadedCount = computed(() => props.methods.length)

// 根据当前页码从缓冲区中切出 20 条
const pagedMethods = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  const end = start + pageSize
  let data = props.methods
  // 应用本地过滤
  if (filterText.value) {
    const q = filterText.value.toLowerCase()
    data = data.filter(
      m => m.class_name.toLowerCase().includes(q) || m.method_name.toLowerCase().includes(q)
    )
  }
  return data.slice(start, end)
})

const handleSelect = (row: ChainMethodSummary | undefined) => {
  if (row) emit('select', row)
}

/** 翻页时检查是否需要加载更多 */
const handlePageChange = (page: number) => {
  currentPage.value = page
  // 当前页的最后一个元素索引
  const neededEnd = page * pageSize
  // 如果需要的元素超出已加载的，且还有更多可加载
  if (neededEnd > props.methods.length && props.total > props.methods.length) {
    emit('loadMore', props.methods.length, BATCH_SIZE)
  }
}

// 当外部 methods 更新时（新批次加载完），检查当前页是否能继续显示
const refreshCurrentPage = () => {
  const maxPage = Math.ceil(props.total / pageSize)
  if (currentPage.value > maxPage) {
    currentPage.value = maxPage
  }
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
