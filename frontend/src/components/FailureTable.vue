<template>
  <el-empty v-if="!rows.length" description="暂无失败规则" />
  <el-table v-else :data="rows">
    <el-table-column type="expand">
      <template #default="{ row }">
        <div class="audit-panel">
          <div>
            <label>激活原因</label>
            <p>{{ row.activationReason }}</p>
          </div>
          <div>
            <label>检查过的模型回复</label>
            <p>{{ row.checkedTurnsText }}</p>
          </div>
          <div>
            <label>没找到的必要事实</label>
            <p>{{ row.missingFactsText }}</p>
          </div>
          <div>
            <label>最接近但不合格的回复</label>
            <p>{{ row.closestReplyText }}</p>
          </div>
          <div>
            <label>扣分影响</label>
            <p>{{ row.deductionImpact }}</p>
          </div>
        </div>
      </template>
    </el-table-column>
    <el-table-column prop="ruleName" label="规则" min-width="170" />
    <el-table-column prop="sourceLabel" label="来源" width="116" />
    <el-table-column prop="severity" label="级别" width="92">
      <template #default="{ row }">
        <el-tag :type="row.severity === 'high' ? 'danger' : 'warning'">{{ row.severity }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="activationTurn" label="激活轮次" width="100" />
    <el-table-column prop="turnIndex" label="证据轮次" width="100" />
    <el-table-column prop="evidence" label="失败原因" min-width="220" show-overflow-tooltip />
    <el-table-column prop="missingFactsText" label="缺失事实" min-width="220" show-overflow-tooltip />
    <el-table-column prop="estimatedDeduction" label="估算扣分" width="100" />
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
const listText = (values, fallback = '暂无记录') => (Array.isArray(values) && values.length ? values.join('、') : fallback)
const closestReplyText = (reply) => {
  if (!reply || !reply.text) return '暂无接近回复'
  const turn = reply.turn_index ?? reply.turnIndex ?? '-'
  return `第 ${turn} 轮：${reply.text}`
}

const rows = computed(() =>
  props.cases.map((item) => {
    const audit = item.audit || {}
    const checkedTurns = item.checked_turns || item.checkedTurns || audit.checked_turns || audit.checkedTurns || []
    const missingFacts = item.missing_facts || item.missingFacts || audit.missing_facts || audit.missingFacts || []
    const closestReply = item.closest_reply || item.closestReply || audit.closest_reply || audit.closestReply || {}
    const estimatedDeduction = item.estimated_deduction_points ?? item.estimatedDeductionPoints ?? audit.estimated_deduction_points ?? audit.estimatedDeductionPoints
    return {
      ruleName: item.rule_name ?? item.ruleName ?? item.rule ?? item.name ?? '-',
      sourceLabel: item.source_label ?? item.sourceLabel ?? item.source ?? '硬规则评分',
      severity: item.severity ?? 'medium',
      activationTurn: item.activation_turn ?? item.activationTurn ?? audit.activation_turn ?? audit.activationTurn ?? '-',
      activationReason: item.activation_reason ?? item.activationReason ?? audit.activation_reason ?? audit.activationReason ?? '暂无激活原因',
      turnIndex: item.turn_index ?? item.turnIndex ?? item.turn ?? '-',
      evidence: item.evidence ?? item.reason ?? '暂无证据',
      checkedTurnsText: listText(checkedTurns.map((turn) => `第 ${turn} 轮`), '暂无检查轮次'),
      missingFactsText: listText(missingFacts, '暂无缺失事实记录'),
      closestReplyText: closestReplyText(closestReply),
      estimatedDeduction: estimatedDeduction !== undefined && estimatedDeduction !== null ? `${estimatedDeduction} 分` : '-',
      deductionImpact: item.deduction_impact ?? item.deductionImpact ?? audit.deduction_impact ?? audit.deductionImpact ?? '暂无扣分影响说明',
      deductionReason: deductionText(item.deduction_reason ?? item.deductionReason ?? item.reason),
      dialogueSnippet: item.dialogue_snippet ?? item.dialogueSnippet ?? item.snippet ?? '',
      suggestion: item.suggestion ?? item.advice ?? '暂无优化建议'
    }
  })
)
</script>

<style scoped>
.audit-panel {
  display: grid;
  gap: 10px;
  padding: 8px 16px 12px 48px;
}

.audit-panel label {
  display: block;
  margin-bottom: 4px;
  color: var(--muted);
  font-size: 12px;
}

.audit-panel p {
  margin: 0;
  color: var(--body-text);
  line-height: 1.6;
  word-break: break-word;
}
</style>
