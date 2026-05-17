<template>
  <section>
    <div class="page-header">
      <div>
        <h1>评测报告 #{{ report.report_id || '-' }}</h1>
        <p>{{ llmJudgeResult.overall_reason || report.explainability?.overall_reason || '报告加载完成后展示总体评估原因。' }}</p>
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
        <div class="panel-title"><h2>任务与模型</h2></div>
        <div class="report-meta-grid">
          <div><span>任务名称</span><strong>{{ taskName }}</strong></div>
          <div><span>用例名称</span><strong>{{ caseName }}</strong></div>
          <div><span>被测模型 provider</span><strong>{{ modelProvider }}</strong></div>
          <div><span>被测模型名称</span><strong>{{ modelName }}</strong></div>
        </div>
        <el-divider />
        <div class="panel-title slim-title"><h2>LLM 评估结论</h2></div>
        <p class="llm-reason">{{ llmJudgeResult.overall_reason || '暂无明显扣分原因' }}</p>
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
      <div class="panel-title"><h2>命中规则与失败规则</h2></div>
      <p class="active-rules-note">{{ activeRulesExplanation }}</p>
      <p v-if="currentStage" class="active-rules-note">当前阶段：{{ currentStage }}。未进入的后续流程不参与当前轮扣分。</p>
      <div class="rule-block">
        <label>命中规则</label>
        <div v-if="matchedRules.length" class="finding-list">
          <el-tag v-for="rule in matchedRules" :key="`matched-${rule}`" type="success">{{ rule }}</el-tag>
        </div>
        <p v-else class="muted">暂无命中规则</p>
      </div>
      <div class="rule-block">
        <label>失败规则</label>
        <div v-if="failedRules.length" class="finding-list failed-rules">
          <el-tag v-for="rule in failedRules" :key="`failed-${rule}`" type="danger">{{ rule }}</el-tag>
        </div>
        <p v-else class="muted">暂无失败规则</p>
      </div>
      <div class="rule-block">
        <label>待完成规则</label>
        <div v-if="pendingRules.length" class="finding-list">
          <el-tag v-for="rule in pendingRules" :key="`pending-${rule}`" type="info">{{ rule }}</el-tag>
        </div>
        <p v-else class="muted">暂无待完成规则</p>
      </div>
      <el-collapse v-if="notApplicableRules.length" class="not-applicable-collapse">
        <el-collapse-item title="未触发规则" name="not-applicable">
          <div class="finding-list">
            <el-tag v-for="rule in notApplicableRules" :key="`not-applicable-${rule}`" type="info">{{ rule }}</el-tag>
          </div>
        </el-collapse-item>
      </el-collapse>
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
      <FailureTable :cases="failureCases" />
    </div>

    <div class="panel report-section">
      <div class="panel-title"><h2>证据链</h2></div>
      <el-empty v-if="!evidenceRows.length" description="暂无明显扣分原因" />
      <el-table v-else :data="evidenceRows">
        <el-table-column prop="turnIndex" label="证据轮次" width="100" />
        <el-table-column prop="userMessage" label="用户发言" min-width="240" show-overflow-tooltip />
        <el-table-column prop="assistantMessage" label="模型回复" min-width="260" show-overflow-tooltip />
        <el-table-column prop="rules" label="命中 / 失败规则" min-width="260" show-overflow-tooltip />
      </el-table>
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
const task = ref({})
const reportCase = ref({})
const reportRun = ref({})
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

const llmJudgeResult = computed(() => report.value.llm_judge_result || report.value.llmJudgeResult || {})
const taskName = computed(() => task.value.name || `任务 #${report.value.task_id || '-'}`)
const caseName = computed(() => reportCase.value.name || `用例 #${report.value.case_id || '-'}`)
const firstMessageDetail = computed(() => (report.value.messages || [])[0]?.detail || {})
const modelProvider = computed(() => reportRun.value.model_provider || firstMessageDetail.value.model_provider || '-')
const modelName = computed(() => reportRun.value.model_name || firstMessageDetail.value.model_name || modelProvider.value || '-')
const keyFindings = computed(() => report.value.explainability?.key_findings || [])
const suggestions = computed(
  () =>
    Array.from(
      new Set([
        ...(report.value.suggestions || []),
        ...(report.value.explainability?.improvement_suggestions || []),
        ...(llmJudgeResult.value.suggestions || [])
      ])
    )
)
const matchedRules = computed(() => report.value.matched_rules || report.value.matchedRules || [])
const failedRules = computed(() => report.value.failed_rules || report.value.failedRules || [])
const failureCases = computed(() => report.value.failure_cases || report.value.failureCases || [])
const activeRules = computed(() => report.value.active_rules || report.value.activeRules || report.value.explainability?.active_rules || {})
const pendingRules = computed(() => report.value.pending_rules || report.value.pendingRules || activeRules.value.pending_rules || activeRules.value.pendingRules || [])
const currentStage = computed(() => report.value.current_stage || report.value.currentStage || report.value.explainability?.current_stage || '')
const activeRulesExplanation = computed(
  () =>
    report.value.active_rules_explanation ||
    report.value.activeRulesExplanation ||
    report.value.explainability?.active_rules_explanation ||
    '本轮仅对当前流程阶段和用户已触发的问题进行评分，后续流程规则暂不扣分。未进入的后续流程不参与当前轮扣分。'
)
const notApplicableRules = computed(() => activeRules.value.not_applicable_rules || activeRules.value.notApplicableRules || [])
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

const deductionText = (value) => (value && value !== '暂无扣分原因' ? value : '暂无明显扣分原因')

const metricRows = computed(() => {
  const explanations = report.value.metric_explanations || report.value.metricExplanations || []
  if (Array.isArray(explanations) && explanations.length) {
    return explanations.map((item, index) => {
      const evidenceTurns = Array.isArray(item.evidence_turns) ? item.evidence_turns : []
      return {
        key: item.metric_key || item.metric_name || index,
        name: item.metric_name || labels[item.metric_key] || item.metric_key || '-',
        score: item.score ?? '-',
        deduction_reason: deductionText(item.deduction_reason),
        evidenceTurnsText: evidenceTurns.length ? evidenceTurns.join('、') : '-',
        evidenceText: item.evidence_text || '暂无证据',
        suggestion: item.suggestion ?? '暂无优化建议'
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
      deduction_reason: deductionText(value.deduction_reason),
      evidenceTurnsText: evidenceTurns.length ? evidenceTurns.join('、') : '-',
      evidenceText: value.evidence_text || (evidenceSnippets.length ? evidenceSnippets.join(' / ') : '暂无证据'),
      suggestion: value.suggestion ?? '暂无优化建议'
    }
  })
})

const evidenceRows = computed(() => {
  const rows = (report.value.evidence_messages || []).map((item, index) => ({
    key: `message-${item.id || index}`,
    turnIndex: item.turn_index ?? item.turnIndex ?? '-',
    userMessage: item.user_message || item.userMessage || '-',
    assistantMessage: item.assistant_message || item.assistantMessage || '-',
    rules: [
      ...(item.matched_rules || item.matchedRules || []).map((rule) => `命中：${rule}`),
      ...(item.missed_rules || item.missedRules || []).map((rule) => `遗漏：${rule}`),
      ...(item.violated_rules || item.violatedRules || []).map((rule) => `违规：${rule}`)
    ].join(' / ') || '暂无规则证据'
  }))
  const llmEvidence = (llmJudgeResult.value.evidence || []).map((item, index) => ({
    key: `llm-${index}`,
    turnIndex: item.turn_index ?? item.turnIndex ?? '-',
    userMessage: item.issue || 'LLM 评估证据',
    assistantMessage: item.quote || '-',
    rules: item.deduction || item.deduction_reason || '暂无明显扣分原因'
  }))
  return [...rows, ...llmEvidence]
})

onMounted(async () => {
  const data = await request.get(`/api/reports/${route.params.id}`)
  report.value = data
  const [taskResult, caseResult, runResult] = await Promise.allSettled([
    request.get(`/api/tasks/${data.task_id}`),
    request.get(`/api/cases?task_id=${data.task_id}`),
    request.get(`/api/runs/${data.run_id}`)
  ])
  if (taskResult.status === 'fulfilled') task.value = taskResult.value
  if (caseResult.status === 'fulfilled') {
    reportCase.value = (caseResult.value || []).find((item) => item.id === data.case_id) || {}
  }
  if (runResult.status === 'fulfilled') reportRun.value = runResult.value
})
</script>

<style scoped>
.report-status {
  margin-bottom: 8px;
}

.report-section {
  margin-top: 16px;
}

.report-meta-grid {
  display: grid;
  gap: 10px;
}

.report-meta-grid div {
  display: grid;
  grid-template-columns: 130px minmax(0, 1fr);
  gap: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}

.report-meta-grid span,
.rule-block label {
  color: var(--muted);
  font-size: 12px;
}

.report-meta-grid strong {
  color: var(--body-text);
  font-size: 14px;
  word-break: break-word;
}

.slim-title {
  margin-bottom: 8px;
}

.llm-reason {
  margin: 0 0 10px;
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

.active-rules-note {
  margin: 0 0 12px;
  color: var(--muted);
}

.rule-block + .rule-block {
  margin-top: 14px;
}

.not-applicable-collapse {
  margin-top: 14px;
}

@media (max-width: 1100px) {
  .formula-grid {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}
</style>
