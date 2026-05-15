<template>
  <el-empty v-if="!rows.length" description="本次评测未触发失败规则" />
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

const rows = computed(() =>
  props.cases.map((item) => ({
    ruleName: item.rule_name ?? item.ruleName ?? item.rule ?? item.name ?? '-',
    severity: item.severity ?? 'medium',
    turnIndex: item.turn_index ?? item.turnIndex ?? item.turn ?? '-',
    evidence: item.evidence ?? item.reason ?? '-',
    deductionReason: item.deduction_reason ?? item.deductionReason ?? item.reason ?? '-',
    dialogueSnippet: item.dialogue_snippet ?? item.dialogueSnippet ?? item.snippet ?? '',
    suggestion: item.suggestion ?? item.advice ?? '-'
  }))
)
</script>
