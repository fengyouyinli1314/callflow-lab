<template>
  <section>
    <div class="page-header">
      <div>
        <h1>评测报告 #{{ report.report_id || '-' }}</h1>
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
          <div><span>被测模型接入方式</span><strong>{{ modelProvider }}</strong></div>
          <div><span>被测模型名称</span><strong>{{ modelName }}</strong></div>
        </div>
        <el-divider />
        <div class="panel-title slim-title"><h2>综合评估结论</h2></div>
        <div class="judge-source">
          <el-tag :type="judgeSourceTagType">{{ judgeSource.label }}</el-tag>
          <span>{{ judgeSource.description }}</span>
        </div>
        <p class="llm-reason">{{ overallReason }}</p>
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
      <el-divider />
      <div class="panel-title slim-title"><h2>规则追溯</h2></div>
      <el-empty v-if="!ruleTraceRows.length" description="暂无规则追溯记录" />
      <el-table v-else :data="ruleTraceRows" class="rule-trace-table">
        <el-table-column prop="ruleName" label="规则" min-width="220" show-overflow-tooltip />
        <el-table-column prop="sourceLabel" label="来源" width="110" />
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag :type="row.statusType">{{ row.statusLabel }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="activationTurnText" label="激活轮次" width="100" />
        <el-table-column prop="activationReason" label="激活原因" min-width="260" show-overflow-tooltip />
        <el-table-column prop="evidenceText" label="证据文本" min-width="260" show-overflow-tooltip />
        <el-table-column prop="deductionReason" label="扣分原因" min-width="240" show-overflow-tooltip />
      </el-table>
    </div>

    <div class="panel report-section">
      <div class="panel-title"><h2>评分公式</h2></div>
      <p class="formula-text">{{ scoreFormula.formulaText }}</p>
      <p class="formula-text muted">{{ scoreFormula.combineFormulaText }}</p>
      <div class="formula-grid">
        <div v-for="item in formulaComponents" :key="item.key" class="formula-item">
          <span>{{ item.name }}</span>
          <strong>{{ item.score }}</strong>
          <small>规则分 {{ item.ruleScore }} / Judge 分 {{ item.judgeScore }}</small>
          <small>{{ item.combineFormulaText }}</small>
          <small>权重 {{ item.weightText }} / 贡献 {{ item.weightedScore }}</small>
        </div>
      </div>
    </div>

    <div class="panel report-section">
      <div class="panel-title"><h2>知识引用与使用评估</h2></div>
      <div class="knowledge-assessment">
        <div>
          <label>模型是否正确使用知识</label>
          <p>{{ knowledgeUsageSummary }}</p>
        </div>
        <div v-if="knowledgeMissed.length">
          <label>未使用相关知识的扣分原因</label>
          <p v-for="item in knowledgeMissed" :key="`missed-knowledge-${item.title}`">
            {{ item.title }}：{{ item.reason || '召回了相关知识，但模型回复未稳定体现关键事实。' }}
          </p>
        </div>
        <div v-if="knowledgeFabricated.length">
          <label>疑似编造知识库外内容</label>
          <p v-for="item in knowledgeFabricated" :key="`fabricated-${item.term || item.reason}`">
            {{ item.term || '风险内容' }}：{{ item.reason || '疑似补充知识库外承诺或处理方式。' }}
          </p>
        </div>
      </div>
      <el-divider />
      <div v-if="knowledgeTurnRows.length" class="knowledge-turn-list">
        <div v-for="row in knowledgeTurnRows" :key="row.key" class="knowledge-turn-row">
          <strong>第 {{ row.turnIndex }} 轮</strong>
          <div v-if="row.refs.length" class="finding-list">
            <el-tag v-for="ref in row.refs" :key="`${row.key}-${ref.title}`" :type="ref.used ? 'success' : 'warning'">
              {{ ref.type }}：{{ ref.title }}{{ ref.used ? '（已使用）' : '（待补充）' }}
            </el-tag>
          </div>
          <p v-else class="muted">本轮未引用知识库</p>
        </div>
      </div>
      <el-empty v-else description="暂无知识引用记录" />
    </div>

    <div class="panel report-section">
      <div class="panel-title"><h2>指标详解</h2></div>
      <el-empty v-if="!metricRows.length" description="暂无详细评分证据" />
      <el-table v-else :data="metricRows">
        <el-table-column prop="name" label="指标名称" width="150" />
        <el-table-column prop="score" label="融合分" width="90" />
        <el-table-column prop="ruleScore" label="规则分" width="90" />
        <el-table-column prop="judgeScore" label="Judge 分" width="100" />
        <el-table-column prop="combineFormulaText" label="融合公式" min-width="210" show-overflow-tooltip />
        <el-table-column prop="deduction_reason" label="扣分原因" min-width="220" show-overflow-tooltip />
        <el-table-column prop="evidenceTurnsText" label="主证据轮次" width="120" />
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
import { providerDisplayName } from '../utils/providerLabels'

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
const caseModeLabels = {
  branch: '分支专项用例',
  full_flow: '完整流程覆盖用例',
  abnormal_exit: '异常终止用例'
}
const caseFocusLabels = {
  normal_delivery: '骑手正常配送主流程',
  unwilling_delivery: '骑手不想配送分支',
  contract_impact: '合同影响咨询分支',
  exit_flying_leg: '退出飞毛腿咨询分支',
  bad_weather: '恶劣天气配送分支',
  ranking_question: '报名排名咨询分支',
  reward_question: '奖励咨询分支',
  course_full_flow: '课程直播完整主流程',
  responsible_person: '负责人正常沟通分支',
  non_responsible_person: '非负责人转达分支',
  busy_merchant: '商家忙碌分支',
  driving_merchant: '商家开车异常终止分支',
  live_type_difference: '直播类型区别咨询分支',
  third_party_config_missing: '第三方配置咨询分支',
  fee_or_coupon: '费用或优惠咨询分支',
  generic: '通用外呼分支'
}
const stageLabels = {
  identity_check: '确认接听人身份',
  upgrade_intro: '说明产品升级',
  awareness_check: '确认是否知晓升级',
  live_difference: '解释标准直播与低延迟直播区别',
  publish_method_check: '确认发布方式',
  configuration_guidance: '指导配置路径',
  fee_check: '说明费用差异',
  enterprise_wechat: '说明企业微信添加方式',
  closing: '结束或稍后再联系',
  case_triggered: '按当前用例分支检查'
}

const displayLabel = (value, map, fallback) => map[value] || fallback || value || '-'
const matchedRuleAliases = {
  '全流程覆盖：确认身份': ['是否确认骑手身份', '确认骑手身份'],
  '全流程覆盖：告知今天飞毛腿合同已生效': [
    '是否告知飞毛腿合同已生效',
    '是否告知飞毛腿合同已签署并生效',
    '是否告知飞毛腿合同已经签署并生效',
    '是否告知飞毛腿合同已经署并生效',
    '必须告知合同已生效',
    '告知飞毛腿合同已生效'
  ],
  '全流程覆盖：说明午晚高峰和单量要求': ['是否说明单日/多日合同完成要求', '是否说明不完成可能影响合同或派单', '必须说明单日/多日完成要求', '必须提醒午晚高峰上线'],
  '全流程覆盖：询问是否可以开始配送': ['是否询问是否可以开始配送', '必须询问是否开始配送', '询问是否可以开始配送'],
  '全流程覆盖：根据骑手态度鼓励挽留或安抚': ['是否根据骑手态度鼓励挽留或安抚', '是否安抚不想配送或情绪不满的骑手', '是否说明雨天订单更多或完成有助于资格'],
  '全流程覆盖：提醒注意安全': ['是否提醒安全', '必须提醒安全', '必须提醒配送安全'],
  '全流程覆盖：说明排名与保资格规则': ['是否说明报名按排名进行', '是否说明不是站长干预', '是否说明报名排名不是站长干预', '是否提醒减少拒单取消超时有助于保住资格'],
  '是否说明报名按排名进行': ['是否说明报名排名不是站长干预'],
  '是否说明不是站长干预': ['是否说明报名排名不是站长干预'],
  '是否说明连续完成多日合同可能有额外奖励': ['回答奖励规则'],
  '全流程覆盖：身份确认': ['是否确认对方是否负责人', '是否识别负责人', '确认对方是否负责人', '机构身份', '确认机构'],
  '全流程覆盖：确认是否知情': ['是否询问对方是否知道低延迟直播', '知道低延迟直播'],
  '全流程覆盖：传达升级内容': ['是否进入产品升级说明', '是否说明新增“标准直播”和“低延迟直播”', '是否说明标准直播和低延迟直播', '是否说明发布页分开显示标准直播和低延迟直播', '是否简短说明升级内容'],
  '全流程覆盖：说明标准直播和低延迟直播区别': ['是否说明标准直播延迟 5-10 秒、费用较低', '是否说明低延迟直播延迟 1-2 秒、互动更流畅', '是否说明低延迟直播适合实时互动', '是否说明标准直播和低延迟直播区别', '是否说明标准直播和低延迟直播', '是否说明标准直播适合大班课', '是否说明低延迟适合小班或实操课'],
  '全流程覆盖：说明价格差异': ['是否说明费用差异或低延迟可能费用更高', '是否说明低延迟可能费用更高', '是否说明低延迟费用可能更高'],
  '全流程覆盖：询问发布方式': ['是否询问发布方式', '是否询问当前发布方式', '是否询问或判断当前发布方式', '是否询问 Web 控制台 / 第三方系统 / SaaS 系统', '是否询问 Web 控制台 / 校务系统A / SaaS系统B'],
  '全流程覆盖：确认前端是否可见并说明配置路径': ['是否说明配置路径', '是否按对应配置路径引导', '是否根据 Web 控制台 / 第三方系统给出不同引导', '是否根据 Web 控制台给出路径', '是否根据第三方系统给出路径', '是否按第三方系统配置路径引导', '若仍看不到，是否说明后台可能未配置并请明天查看'],
  '全流程覆盖：检查学员端费用/加速线路费': ['是否检查学员端费用/加速线路费', '是否说明低延迟也要适用该费用'],
  '全流程覆盖：企业微信添加': ['是否说明企业微信添加逻辑', '是否不泄露无关信息'],
  '全流程覆盖：结束确认': ['是否确认是否还有问题', '是否在结束前确认是否还有问题', '是否礼貌结束', '是否给商家发言机会', '不能不给商家发言机会'],
  '是否说明标准直播延迟 5-10 秒、费用较低': ['是否说明标准直播和低延迟直播区别'],
  '是否说明低延迟直播延迟 1-2 秒、互动更流畅': ['是否说明低延迟直播适合实时互动'],
  '是否说明低延迟可能费用更高': ['是否说明费用差异或低延迟可能费用更高'],
  '是否询问当前发布方式': ['是否询问发布方式'],
  '是否说明配置路径': ['是否按对应配置路径引导']
}
const isForbiddenLikeRule = (ruleName) =>
  ['禁止', '不能', '避免承诺', '避免编造', '不继续推销', '不强行'].some((term) => String(ruleName || '').includes(term))
const isPassedLegacyActiveRow = (item) => {
  const status = item.status || 'active'
  const ruleName = item.rule_name || item.ruleName || ''
  const evidenceText = item.evidence_text || item.evidenceText || ''
  return status === 'active' && isForbiddenLikeRule(ruleName) && !evidenceText
}
const isHiddenGuardrailRow = (item) => (item.source || item.source_label || item.sourceLabel || '').includes('hidden_guardrail') || (item.source_label || item.sourceLabel || '').includes('后台护栏')
const readableRuleStatus = (item) => {
  if (isPassedLegacyActiveRow(item)) return { status: 'passed', label: '已通过' }
  const status = item.status || 'active'
  return { status, label: item.status_label || item.statusLabel || status || '-' }
}
const readableActivationReason = (item) => {
  const rawReason = String(item.activation_reason || item.activationReason || '-')
  const caseMode = item.case_mode || item.caseMode || Object.keys(caseModeLabels).find((key) => rawReason.includes(key)) || ''
  const caseFocus = item.case_focus || item.caseFocus || Object.keys(caseFocusLabels).find((key) => rawReason.includes(key)) || ''
  const stage = item.current_stage || item.currentStage || Object.keys(stageLabels).find((key) => rawReason.includes(key)) || ''
  const hasInternalCaseTags =
    rawReason.includes('当前用例模式为') ||
    Object.keys(caseModeLabels).some((key) => rawReason.includes(key)) ||
    Object.keys(caseFocusLabels).some((key) => rawReason.includes(key))
  if (hasInternalCaseTags && caseMode) {
    return `当前是“${displayLabel(caseMode, caseModeLabels, '当前用例')}”，评测目标是“${displayLabel(
      caseFocus,
      caseFocusLabels,
      '当前用例目标'
    )}”，因此这条用例规则需要检查。`
  }
  const hasInternalStageTags = Object.keys(stageLabels).some((key) => rawReason.includes(key))
  if (hasInternalStageTags && stage) {
    return rawReason.replace(stage, displayLabel(stage, stageLabels, '当前流程阶段'))
  }
  return rawReason
}
const readableRuleDeductionReason = (item) => {
  const rawReason = item.deduction_reason || item.deductionReason || ''
  if (isPassedLegacyActiveRow(item) && (!rawReason || rawReason === '该规则未通过检查。')) {
    return '已检查，未发现违规，不扣分。'
  }
  return deductionText(rawReason)
}

const grade = computed(() => {
  const score = Number(report.value.total_score ?? 0)
  if (score >= 90) return { label: '优秀', type: 'success' }
  if (score >= 80) return { label: '良好', type: 'success' }
  if (score >= 60) return { label: '及格', type: 'warning' }
  return { label: '待优化', type: 'danger' }
})

const llmJudgeResult = computed(() => report.value.llm_judge_result || report.value.llmJudgeResult || {})
const readableOverallReason = (reason = '') => {
  const text = String(reason || '').trim()
  if (!text) return ''
  const matched = text.match(/命中\s*(\d+)\s*条规则，失败\s*(\d+)\s*条/)
  if (matched) {
    return `规则辅助评审基于本轮评分结果生成综合结论：命中 ${matched[1]} 条规则，失败 ${matched[2]} 条。`
  }
  return text
}
const overallReason = computed(
  () =>
    readableOverallReason(llmJudgeResult.value.overall_reason) ||
    readableOverallReason(report.value.explainability?.overall_reason) ||
    '报告加载完成后展示总体评估原因。'
)
const readableFallbackReasonText = (reason = '') => {
  const text = String(reason || '').trim()
  if (!text) return ''
  if (text.startsWith('openai_compatible evaluator HTTP error')) {
    const status = text.replace('openai_compatible evaluator HTTP error', '').trim()
    return `外部评审器 HTTP 请求失败${status ? `（状态码 ${status}）` : ''}`
  }
  if (text === 'openai_compatible evaluator request failed') return '外部评审器请求失败'
  if (text === 'openai_compatible evaluator returned non-JSON API response') return '外部评审器接口响应不是 JSON'
  if (text === 'openai_compatible evaluator API error response') return '外部评审器接口返回错误'
  if (text === 'openai_compatible evaluator returned empty response') return '外部评审器返回为空'
  if (text === 'openai_compatible evaluator returned invalid JSON response') return '外部评审器没有返回有效 JSON 评分结构'
  if (text === 'openai_compatible evaluator returned empty or invalid response') return '外部评审器返回为空或不是有效结构化结果'
  return text
}
const judgeSource = computed(() => {
  const source = report.value.judge_source || report.value.judgeSource || llmJudgeResult.value.judge_source || llmJudgeResult.value.judgeSource || {}
  const provider = source.provider || llmJudgeResult.value.provider || 'mock'
  const fallbackUsed = Boolean(source.fallback_used ?? source.fallbackUsed ?? llmJudgeResult.value.fallback_used)
  const isMock = source.source_type === 'mock_fallback' || provider === 'mock' || fallbackUsed
  const fallbackReason = source.fallback_reason || source.fallbackReason || llmJudgeResult.value.fallback_reason || ''
  const readableFallbackReason = readableFallbackReasonText(fallbackReason)
  const fallbackDescription = readableFallbackReason
    ? `本处为报告端规则辅助评审，基于规则评分结果生成综合说明；被测模型回复仍按所选接入方式生成。评审器外部调用未采用，原因：${readableFallbackReason}。`
    : '本处为报告端规则辅助评审，基于规则评分结果生成综合说明；被测模型回复仍按所选接入方式生成。'
  return {
    label:
      source.label === '本地兜底评审' || (isMock && source.label === '真实大模型评审')
        ? '规则辅助评审'
        : source.label || (isMock ? '规则辅助评审' : '大模型辅助评审'),
    description:
      (source.description || '')
        .replace('当前为本地兜底评审：基于硬规则结果生成语义解释。', fallbackDescription)
        .replace('请求真实 Judge 未完成，已自动回退为本地兜底评审。', fallbackDescription) ||
      (isMock
        ? fallbackDescription
        : '本处使用外部评审器结合规则结果生成综合说明。'),
    configHint: '',
    sourceType: source.source_type || source.sourceType || (isMock ? 'mock_fallback' : 'openai_compatible')
  }
})
const judgeSourceTagType = computed(() => (judgeSource.value.sourceType === 'mock_fallback' ? 'info' : 'success'))
const taskName = computed(() => task.value.name || `任务 #${report.value.task_id || '-'}`)
const caseName = computed(() => reportCase.value.name || `用例 #${report.value.case_id || '-'}`)
const firstMessageDetail = computed(() => (report.value.messages || [])[0]?.detail || {})
const rawModelProvider = computed(() => reportRun.value.model_provider || firstMessageDetail.value.model_provider || '')
const modelProvider = computed(() => providerDisplayName(rawModelProvider.value))
const modelName = computed(() => {
  const rawName = reportRun.value.model_name || firstMessageDetail.value.model_name || ''
  if (!rawName || rawName === rawModelProvider.value) return providerDisplayName(rawModelProvider.value)
  return rawName
})
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
const currentStage = computed(() => {
  const rawStage = report.value.current_stage || report.value.currentStage || report.value.explainability?.current_stage || ''
  return rawStage ? displayLabel(rawStage, stageLabels, rawStage) : ''
})
const activeRulesExplanation = computed(
  () =>
    report.value.active_rules_explanation ||
    report.value.activeRulesExplanation ||
    report.value.explainability?.active_rules_explanation ||
    '本轮仅对当前流程阶段和用户已触发的问题进行评分，后续流程规则暂不扣分。未进入的后续流程不参与当前轮扣分。'
)
const notApplicableRules = computed(() => activeRules.value.not_applicable_rules || activeRules.value.notApplicableRules || [])
const ruleTrace = computed(() => report.value.rule_trace || report.value.ruleTrace || report.value.explainability?.rule_trace || {})
const ruleTraceRows = computed(() => {
  const rows = ruleTrace.value.rows || ruleTrace.value.ruleTraceRows || []
  if (!Array.isArray(rows)) return []
  const resolvedAliases = new Set()
  rows.forEach((item) => {
    const ruleName = item.rule_name || item.ruleName || ''
    if ((item.status || '') === 'matched') {
      resolvedAliases.add(ruleName)
      ;(matchedRuleAliases[ruleName] || []).forEach((alias) => resolvedAliases.add(alias))
    }
  })
  return rows
    .filter((item) => {
      const ruleName = item.rule_name || item.ruleName || ''
      if (isHiddenGuardrailRow(item) && (item.status || '') !== 'failed') return false
      return !((item.status || '') === 'untriggered' && resolvedAliases.has(ruleName))
    })
    .map((item, index) => {
      const status = readableRuleStatus(item)
      return {
        key: `${item.rule_name || item.ruleName || index}-${index}`,
        ruleName: item.rule_name || item.ruleName || '-',
        sourceLabel: item.source_label || item.sourceLabel || item.source || '-',
        status: status.status,
        statusLabel: status.label,
        statusType: ruleStatusType(status.status),
        activationTurnText: item.activation_turn || item.activationTurn || '-',
        activationReason: readableActivationReason(item),
        evidenceText: item.evidence_text || item.evidenceText || '暂无证据文本',
        deductionReason: readableRuleDeductionReason(item)
      }
    })
})
const knowledgeAssessment = computed(() => llmJudgeResult.value.knowledge_assessment || llmJudgeResult.value.knowledgeAssessment || {})
const knowledgeMissed = computed(() => knowledgeAssessment.value.missed_knowledge || knowledgeAssessment.value.missedKnowledge || [])
const knowledgeFabricated = computed(() => knowledgeAssessment.value.fabricated_knowledge || knowledgeAssessment.value.fabricatedKnowledge || [])
const usedKnowledgeTitles = computed(() => new Set(knowledgeAssessment.value.used_knowledge || knowledgeAssessment.value.usedKnowledge || []))
const retrievedKnowledgeTitles = computed(() => knowledgeAssessment.value.retrieved_titles || knowledgeAssessment.value.retrievedTitles || [])
const knowledgeUsageSummary = computed(() => {
  if (!retrievedKnowledgeTitles.value.length) return '本次报告没有记录知识召回。'
  if (!knowledgeMissed.value.length && !knowledgeFabricated.value.length) return '模型已使用本次召回的关键知识，未发现明显知识外编造。'
  if (knowledgeMissed.value.length && knowledgeFabricated.value.length) return '模型存在未使用相关知识和疑似知识外编造，需要补齐。'
  if (knowledgeMissed.value.length) return '模型存在已召回但未稳定使用的关键知识。'
  return '模型存在疑似知识库外内容。'
})
const knowledgeTypeLabel = (type) => {
  const labels = {
    opening: 'Opening',
    flow: 'Flow',
    faq: 'FAQ',
    constraint: 'Constraint'
  }
  return labels[type] || type || 'Knowledge'
}
const knowledgeTurnRows = computed(() =>
  (report.value.messages || []).map((item, index) => {
    const detail = item.detail || {}
    const refs = (detail.retrieved_knowledge || detail.retrievedKnowledge || []).map((chunk) => ({
      title: chunk.title || '未命名知识',
      type: knowledgeTypeLabel(chunk.chunk_type || chunk.chunkType),
      used: usedKnowledgeTitles.value.has(chunk.title)
    }))
    return {
      key: item.id || `knowledge-turn-${index}`,
      turnIndex: item.turn_index ?? item.turnIndex ?? index + 1,
      refs
    }
  })
)
const scoreFormula = computed(() => {
  const formula = report.value.score_formula || report.value.explainability?.score_formula || {}
  return {
    formulaText:
      formula.formula_text ||
      '总分 = 任务完成度 * 0.25 + 指令遵循率 * 0.20 + 外呼流程覆盖率 * 0.20 + 约束遵守率 * 0.15 + 上下文一致性 * 0.10 + 回复质量 * 0.10',
    combineFormulaText: formula.combine_formula_text || '各指标融合分 = rule_score * 0.7 + judge_score * 0.3',
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
    const ruleScore = Number(component.rule_score ?? score)
    const judgeScore = Number(component.judge_score ?? score)
    return {
      key,
      name: component.metric_name || labels[key] || key,
      score: Number.isFinite(score) ? score.toFixed(1) : '-',
      ruleScore: Number.isFinite(ruleScore) ? ruleScore.toFixed(1) : '-',
      judgeScore: Number.isFinite(judgeScore) ? judgeScore.toFixed(1) : '-',
      combineFormulaText: component.combine_formula_text || component.combineFormulaText || 'rule_score * 0.7 + judge_score * 0.3',
      weightText: `${Math.round(Number(weight) * 100)}%`,
      weightedScore: Number.isFinite(weightedScore) ? weightedScore.toFixed(1) : '-'
    }
  })
)

const deductionText = (value) => (value && value !== '暂无扣分原因' ? value : '暂无明显扣分原因')
const ruleStatusType = (status) => {
  if (status === 'matched') return 'success'
  if (status === 'passed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'pending') return 'info'
  if (status === 'untriggered') return 'warning'
  return 'info'
}

const splitEvidenceText = (value) =>
  String(value || '')
    .split(/\s+\/\s+/)
    .map((item) => item.trim())
    .filter(Boolean)

const primaryEvidenceIndex = (metricKey, turns, parts) => {
  const count = Math.max(turns.length, parts.length)
  if (count <= 1) return 0
  if (metricKey === 'task_completion' || metricKey === 'call_flow_coverage') {
    return count - 1
  }
  if (metricKey === 'instruction_following') {
    const nonOpeningIndex = turns.findIndex((turn) => Number(turn) > 0)
    return nonOpeningIndex >= 0 ? nonOpeningIndex : 0
  }
  if (metricKey === 'context_consistency' || metricKey === 'response_quality') {
    return count - 1
  }
  return 0
}

const metricEvidenceSummary = (metricKey, rawTurns, rawText, rawSnippets = []) => {
  const turns = Array.isArray(rawTurns)
    ? rawTurns.filter((turn) => turn !== null && turn !== undefined && turn !== '')
    : []
  const parts = splitEvidenceText(rawText)
  const snippetParts = Array.isArray(rawSnippets) ? rawSnippets.flatMap(splitEvidenceText) : []
  const allParts = parts.length ? parts : snippetParts
  const fallbackText = String(rawText || '').trim() || '暂无证据'
  if (!turns.length && !allParts.length) {
    return { turnText: '-', text: fallbackText }
  }
  const index = primaryEvidenceIndex(metricKey, turns, allParts)
  return {
    turnText: turns[index] ?? turns[0] ?? '-',
    text: allParts[index] ?? allParts[0] ?? fallbackText
  }
}

const metricRows = computed(() => {
  const explanations = report.value.metric_explanations || report.value.metricExplanations || []
  if (Array.isArray(explanations) && explanations.length) {
    return explanations.map((item, index) => {
      const evidenceTurns = Array.isArray(item.evidence_turns) ? item.evidence_turns : []
      const evidence = metricEvidenceSummary(item.metric_key, evidenceTurns, item.evidence_text)
      return {
        key: item.metric_key || item.metric_name || index,
        name: item.metric_name || labels[item.metric_key] || item.metric_key || '-',
        score: item.score ?? '-',
        ruleScore: item.rule_score ?? item.ruleScore ?? '-',
        judgeScore: item.judge_score ?? item.judgeScore ?? item.llm_score ?? item.llmScore ?? '-',
        combineFormulaText: item.combine_formula_text || item.combineFormulaText || 'rule_score * 0.7 + judge_score * 0.3',
        deduction_reason: deductionText(item.deduction_reason),
        evidenceTurnsText: evidence.turnText,
        evidenceText: evidence.text,
        suggestion: item.suggestion ?? '暂无优化建议'
      }
    })
  }
  const details = report.value.metric_details || report.value.metricDetails || {}
  return Object.entries(details).map(([key, value]) => {
    const evidenceTurns = Array.isArray(value.evidence_turns) ? value.evidence_turns : []
    const evidenceSnippets = Array.isArray(value.evidence_snippets) ? value.evidence_snippets : []
    const evidence = metricEvidenceSummary(key, evidenceTurns, value.evidence_text, evidenceSnippets)
    return {
      key,
      name: labels[key] || key,
      score: value.score ?? '-',
      ruleScore: value.rule_score ?? value.ruleScore ?? value.score ?? '-',
      judgeScore: value.judge_score ?? value.judgeScore ?? value.llm_score ?? value.llmScore ?? '-',
      combineFormulaText: value.combine_formula_text || value.combineFormulaText || 'rule_score * 0.7 + judge_score * 0.3',
      deduction_reason: deductionText(value.deduction_reason),
      evidenceTurnsText: evidence.turnText,
      evidenceText: evidence.text,
      suggestion: value.suggestion ?? '暂无优化建议'
    }
  })
})

const evidenceRows = computed(() => {
  const rows = (report.value.evidence_messages || [])
    .filter((item) => {
      const relatedRules = item.related_rules || item.relatedRules || []
      const matched = item.matched_rules || item.matchedRules || []
      const missed = item.missed_rules || item.missedRules || []
      const violated = item.violated_rules || item.violatedRules || []
      return item.source !== 'conversation' && (relatedRules.length || matched.length || missed.length || violated.length || item.issue)
    })
    .map((item, index) => {
      const relatedRules = item.related_rules || item.relatedRules || []
      return {
        key: `message-${item.id || index}`,
        turnIndex: item.turn_index ?? item.turnIndex ?? '-',
        userMessage: item.user_message || item.userMessage || '-',
        assistantMessage: item.assistant_message || item.assistantMessage || '-',
        rules:
          [
            ...relatedRules.map((rule) => `关联：${rule}`),
            ...(item.matched_rules || item.matchedRules || []).map((rule) => `命中：${rule}`),
            ...(item.missed_rules || item.missedRules || []).map((rule) => `遗漏：${rule}`),
            ...(item.violated_rules || item.violatedRules || []).map((rule) => `违规：${rule}`)
          ].join(' / ') || item.issue || '-'
      }
    })
  const llmEvidence = (llmJudgeResult.value.evidence || []).map((item, index) => ({
    key: `llm-${index}`,
    turnIndex: item.turn_index ?? item.turnIndex ?? '-',
    userMessage: item.issue || '综合评估证据',
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

.judge-source {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 8px;
  color: var(--body-text);
  line-height: 1.5;
}

.judge-source-hint {
  margin: 0 0 10px;
  color: var(--muted);
  font-size: 12px;
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
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  background: rgba(8, 13, 22, 0.92);
}

.not-applicable-collapse :deep(.el-collapse-item__wrap),
.not-applicable-collapse :deep(.el-collapse-item__content),
.not-applicable-collapse :deep(.el-collapse-item__header) {
  background: rgba(8, 13, 22, 0.92);
  color: var(--body-text);
  border-color: var(--line);
}

.not-applicable-collapse :deep(.el-collapse-item__header) {
  padding: 0 12px;
  font-weight: 650;
}

.not-applicable-collapse :deep(.el-collapse-item__content) {
  padding: 12px;
}

.not-applicable-collapse :deep(.el-tag.el-tag--info) {
  color: #cbd5e1;
  background: rgba(148, 163, 184, 0.12);
  border-color: rgba(148, 163, 184, 0.18);
}

.knowledge-assessment {
  display: grid;
  gap: 12px;
}

.knowledge-assessment label {
  display: block;
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 6px;
}

.knowledge-assessment p {
  margin: 0;
  line-height: 1.6;
}

.knowledge-assessment p + p {
  margin-top: 6px;
}

.knowledge-turn-list {
  display: grid;
  gap: 12px;
}

.knowledge-turn-row {
  display: grid;
  gap: 8px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}

.knowledge-turn-row:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

@media (max-width: 1100px) {
  .formula-grid {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}
</style>
