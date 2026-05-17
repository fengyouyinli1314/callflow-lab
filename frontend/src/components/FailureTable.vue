<template>
  <el-empty v-if="!rows.length" description="暂无失败规则" />
  <el-table v-else :data="rows">
    <el-table-column prop="ruleName" label="规则" min-width="170" />
    <el-table-column prop="severity" label="级别" width="92">
      <template #default="{ row }">
        <el-tag :type="row.severity === 'high' ? 'danger' : 'warning'">{{ row.severity }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="turnIndex" label="证据轮次" width="100" />
    <el-table-column prop="evidence" label="失败原因" min-width="220" show-overflow-tooltip />
    <el-table-column prop="deductionReason" label="扣分原因" min-width="220" show-overflow-tooltip />
    <el-table-column prop="dialogueSnippet" label="对话片段" min-width="260" show-overflow-tooltip />
    <el-table-column prop="suggestion" label="优化建议" min-width="260" show-overflow-tooltip />
  </el-table>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  cases: { type: Array, default: () => [] }
})

const deductionText = (value) => (value && value !== '暂无扣分原因' ? value : '暂无明显扣分原因')

const rows = computed(() =>
  props.cases.map((item) => ({
    ruleName: item.rule_name ?? item.ruleName ?? item.rule ?? item.name ?? '-',
    severity: item.severity ?? 'medium',
    turnIndex: item.turn_index ?? item.turnIndex ?? item.turn ?? '-',
    evidence: item.evidence ?? item.reason ?? '暂无证据',
    deductionReason: deductionText(item.deduction_reason ?? item.deductionReason ?? item.reason),
    dialogueSnippet: item.dialogue_snippet ?? item.dialogueSnippet ?? item.snippet ?? '',
    suggestion: item.suggestion ?? item.advice ?? '暂无优化建议'
  }))
)
</script>
