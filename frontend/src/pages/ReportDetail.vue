<template>
  <section>
    <div class="page-header">
      <div>
        <h1>评测报告 #{{ report.report_id || '-' }}</h1>
        <p>{{ report.explainability?.overall_reason || '报告加载完成后展示总体评估原因。' }}</p>
      </div>
      <el-button :icon="Back" @click="$router.push('/runs')">返回评测台</el-button>
    </div>

    <div class="grid two">
      <div class="panel">
        <div class="panel-title">
          <h2>总分与雷达图</h2>
          <el-tag :type="grade.type">{{ grade.label }}</el-tag>
        </div>
        <div class="status-row report-status">
          <div class="score-large">{{ report.total_score ?? 0 }}</div>
          <div class="muted">
            平均响应 {{ report.avg_latency_ms ?? 0 }} ms<br />
            对话轮数 {{ report.total_turns ?? 0 }}<br />
            失败规则 {{ report.failed_rule_count ?? failedRules.length }} 条
          </div>
        </div>
        <ScoreRadar :report="report" />
      </div>

      <div class="panel">
        <div class="panel-title"><h2>关键发现</h2></div>
        <div v-if="keyFindings.length" class="finding-list">
          <el-tag v-for="item in keyFindings" :key="item" type="info">{{ item }}</el-tag>
        </div>
        <el-empty v-else description="暂无关键发现" />
        <el-divider />
        <div v-if="suggestions.length" class="suggestions">
          <p v-for="item in suggestions" :key="item">{{ item }}</p>
        </div>
        <p v-else class="muted">暂无优化建议</p>
      </div>
    </div>

    <div class="panel report-section">
      <div class="panel-title"><h2>评分公式</h2></div>
      <p class="formula-text">{{ scoreFormula.formulaText }}</p>
      <div class="formula-grid">
        <div v-for="item in formulaComponents" :key="item.key" class="formula-item">
          <span>{{ item.name }}</span>
          <strong>{{ item.score }}</strong>
          <small>权重 {{ item.weightText }} / 贡献 {{ item.weightedScore }}</small>
        </div>
      </div>
    </div>

    <div class="panel report-section">
      <div class="panel-title"><h2>指标详解</h2></div>
      <el-empty v-if="!metricRows.length" description="暂无详细评分证据" />
      <el-table v-else :data="metricRows">
        <el-table-column prop="name" label="指标名称" width="150" />
        <el-table-column prop="score" label="分数" width="90" />
        <el-table-column prop="deduction_reason" label="扣分原因" min-width="220" show-overflow-tooltip />
        <el-table-column prop="evidenceTurnsText" label="证据轮次" width="120" />
        <el-table-column prop="evidenceText" label="对话片段" min-width="260" show-overflow-tooltip />
        <el-table-column prop="suggestion" label="优化建议" min-width="260" show-overflow-tooltip />
      </el-table>
    </div>

    <div class="panel report-section">
      <div class="panel-title"><h2>失败案例</h2></div>
      <div v-if="failedRules.length" class="finding-list failed-rules">
        <el-tag v-for="rule in failedRules" :key="rule" type="danger">{{ rule }}</el-tag>
      </div>
      <FailureTable :cases="failureCases" />
    </div>

    <div class="panel report-section">
      <div class="panel-title"><h2>完整对话证据</h2></div>
      <ConversationTimeline :messages="report.messages || []" />
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Back } from '@element-plus/icons-vue'
import request from '../api/request'
import ConversationTimeline from '../components/ConversationTimeline.vue'
import FailureTable from '../components/FailureTable.vue'
import ScoreRadar from '../components/ScoreRadar.vue'

const route = useRoute()
const report = ref({
  explainability: {},
  metric_details: {},
  metric_explanations: [],
  suggestions: [],
  failed_rules: [],
  failed_rule_count: 0,
  call_flow_coverage: 0,
  constraint_compliance: 0,
  messages: [],
  failure_cases: [],
  score_formula: {}
})
const labels = {
  task_completion: '任务完成度',
  instruction_following: '指令遵循率',
  call_flow_coverage: '外呼流程覆盖率',
  constraint_compliance: '约束遵守率',
  context_consistency: '上下文一致性',
  safety_compliance: '安全合规性',
  response_quality: '回复质量'
}

const grade = computed(() => {
  const score = Number(report.value.total_score ?? 0)
  if (score >= 90) return { label: '优秀', type: 'success' }
  if (score >= 60) return { label: '及格', type: 'warning' }
  return { label: '待优化', type: 'danger' }
})

const keyFindings = computed(() => report.value.explainability?.key_findings || [])
const suggestions = computed(
  () => Array.from(new Set([...(report.value.suggestions || []), ...(report.value.explainability?.improvement_suggestions || [])]))
)
const failedRules = computed(() => report.value.failed_rules || report.value.failedRules || [])
const failureCases = computed(() => report.value.failure_cases || report.value.failureCases || [])
const scoreFormula = computed(() => {
  const formula = report.value.score_formula || report.value.explainability?.score_formula || {}
  return {
    formulaText:
      formula.formula_text ||
      '总分 = 任务完成度 * 0.25 + 指令遵循率 * 0.20 + 外呼流程覆盖率 * 0.20 + 约束遵守率 * 0.15 + 上下文一致性 * 0.10 + 回复质量 * 0.10',
    components: formula.components || {},
    weights: formula.weights || {
      task_completion: 0.25,
      instruction_following: 0.2,
      call_flow_coverage: 0.2,
      constraint_compliance: 0.15,
      context_consistency: 0.1,
      response_quality: 0.1
    }
  }
})

const formulaComponents = computed(() =>
  Object.entries(scoreFormula.value.weights).map(([key, weight]) => {
    const component = scoreFormula.value.components?.[key] || {}
    const score = Number(component.score ?? report.value[key] ?? 0)
    const weightedScore = Number(component.weighted_score ?? score * weight)
    return {
      key,
      name: component.metric_name || labels[key] || key,
      score: Number.isFinite(score) ? score.toFixed(1) : '-',
      weightText: `${Math.round(Number(weight) * 100)}%`,
      weightedScore: Number.isFinite(weightedScore) ? weightedScore.toFixed(1) : '-'
    }
  })
)

const metricRows = computed(() => {
  const explanations = report.value.metric_explanations || report.value.metricExplanations || []
  if (Array.isArray(explanations) && explanations.length) {
    return explanations.map((item, index) => {
      const evidenceTurns = Array.isArray(item.evidence_turns) ? item.evidence_turns : []
      return {
        key: item.metric_key || item.metric_name || index,
        name: item.metric_name || labels[item.metric_key] || item.metric_key || '-',
        score: item.score ?? '-',
        deduction_reason: item.deduction_reason ?? '暂无扣分原因',
        evidenceTurnsText: evidenceTurns.length ? evidenceTurns.join('、') : '-',
        evidenceText: item.evidence_text || '-',
        suggestion: item.suggestion ?? '-'
      }
    })
  }
  const details = report.value.metric_details || report.value.metricDetails || {}
  return Object.entries(details).map(([key, value]) => {
    const evidenceTurns = Array.isArray(value.evidence_turns) ? value.evidence_turns : []
    const evidenceSnippets = Array.isArray(value.evidence_snippets) ? value.evidence_snippets : []
    return {
      key,
      name: labels[key] || key,
      score: value.score ?? '-',
      deduction_reason: value.deduction_reason ?? '暂无扣分原因',
      evidenceTurnsText: evidenceTurns.length ? evidenceTurns.join('、') : '-',
      evidenceText: value.evidence_text || (evidenceSnippets.length ? evidenceSnippets.join(' / ') : '-'),
      suggestion: value.suggestion ?? '-'
    }
  })
})

onMounted(async () => {
  report.value = await request.get(`/api/reports/${route.params.id}`)
})
</script>

<style scoped>
.report-status {
  margin-bottom: 8px;
}

.report-section {
  margin-top: 16px;
}

.finding-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.suggestions {
  display: grid;
  gap: 8px;
}

.suggestions p {
  margin: 0;
}

.formula-text {
  margin: 0 0 12px;
  color: var(--body-text);
}

.formula-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
}

.formula-item {
  display: grid;
  gap: 2px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: rgba(22, 32, 51, 0.46);
}

.formula-item span {
  color: var(--muted);
  font-size: 12px;
}

.formula-item strong {
  color: var(--cyan);
  font-size: 22px;
}

.formula-item small {
  color: var(--weak);
}

.failed-rules {
  margin-bottom: 12px;
}

@media (max-width: 1100px) {
  .formula-grid {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}
</style>
