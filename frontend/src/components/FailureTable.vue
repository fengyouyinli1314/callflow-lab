<template>
  <el-table :data="cases" empty-text="暂无失败案例">
    <el-table-column prop="rule_name" label="规则" min-width="160" />
    <el-table-column prop="severity" label="级别" width="90">
      <template #default="{ row }">
        <el-tag :type="row.severity === 'high' ? 'danger' : 'warning'">{{ row.severity }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="turn_index" label="证据轮次" width="100" />
    <el-table-column prop="evidence" label="失败原因" min-width="220" />
    <el-table-column prop="suggestion" label="优化建议" min-width="240" />
  </el-table>
</template>

<script setup>
defineProps({
  cases: { type: Array, default: () => [] }
})
</script>
