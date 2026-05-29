<template>
  <div class="sql-analyzer" v-loading="loading">
    <el-table :data="data" style="width: 100%" v-if="data.length > 0">
      <el-table-column prop="table" label="表名" width="200" />
      <el-table-column prop="operation" label="操作类型" width="150">
        <template #default="{ row }">
          <el-tag :type="getOperationType(row.operation)">
            {{ row.operation }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="count" label="调用次数" width="150" />
    </el-table>
    
    <el-empty v-else description="暂无SQL数据" />
  </div>
</template>

<script setup lang="ts">
defineProps<{
  data: any[]
  loading?: boolean
}>()

const getOperationType = (operation: string) => {
  const typeMap: Record<string, any> = {
    SELECT: 'primary',
    INSERT: 'success',
    UPDATE: 'warning',
    DELETE: 'danger'
  }
  return typeMap[operation] || 'info'
}
</script>

<style scoped>
.sql-analyzer {
  padding: 20px;
}
</style>
