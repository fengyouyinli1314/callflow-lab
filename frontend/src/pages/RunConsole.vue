<template>
  <section>
    <div class="page-header">
      <div>
        <h1>开始评测</h1>
        <p>选择任务、用例和模型 provider 后，点击开始评测执行多轮对话、规则评分与报告生成。</p>
      </div>
    </div>

    <div class="grid run-layout">
      <div class="panel config-panel">
        <div class="panel-title"><h2>评测配置</h2></div>
        <el-form label-position="top">
          <el-form-item label="评测任务">
            <el-select v-model="taskId" style="width: 100%" @change="loadCases">
              <el-option v-for="task in tasks" :key="task.id" :label="task.name" :value="task.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="测试用例">
            <el-select v-model="caseId" style="width: 100%">
              <el-option v-for="item in cases" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <div class="case-actions">
            <el-button :icon="Plus" @click="openCreateCase">新建用例</el-button>
            <el-button :icon="Edit" :disabled="!selectedCase" @click="openEditCase">编辑当前用例</el-button>
          </div>
          <el-form-item label="被测模型 provider">
            <el-select v-model="modelProvider" style="width: 100%">
              <el-option
                v-for="provider in providerOptions"
                :key="provider.value"
                :label="provider.label"
                :value="provider.value"
              />
            </el-select>
          </el-form-item>
          <p class="provider-note">
            mock_fallback 仅用于演示兜底，不是真实 AI；openai_compatible 和 custom_endpoint 才是真实模型接入方式。
          </p>
          <div class="debug-meta">
            <span>task_type: {{ selectedTask?.task_type || 'unknown' }}</span>
            <span>model_provider: {{ displayProvider(result?.provider_used || result?.model_provider || modelProvider) }}</span>
            <span>model_name: {{ displayProvider(result?.model_name || modelName) }}</span>
          </div>
          <el-button
            type="primary"
            :loading="running"
            :disabled="running"
            :icon="running ? Loading : VideoPlay"
            style="width: 100%"
            @click="start"
          >
            {{ running ? '评测中...' : '开始评测' }}
          </el-button>
          <div v-if="running" class="run-stage-hint">
            <span class="pulse-dot" />
            <span>{{ currentRunStage }}</span>
          </div>
        </el-form>

        <template v-if="selectedCase">
          <el-divider />
          <div class="case-summary">
            <div class="summary-row">
              <span>难度</span>
              <el-tag>{{ selectedCase.difficulty }}</el-tag>
            </div>
            <div class="summary-row">
              <span>用例模式</span>
              <el-tag type="info">{{ caseModeLabel(selectedCase.case_mode) }}</el-tag>
            </div>
            <div class="summary-row">
              <span>安全上限</span>
              <strong>{{ selectedCase.max_turns }} 轮</strong>
            </div>
            <div>
              <label>当前目标</label>
              <p>{{ currentGoalText }}</p>
            </div>
            <div>
              <label>用户画像</label>
              <p>{{ selectedCase.user_profile }}</p>
            </div>
            <div>
              <label>用户首句回应</label>
              <p>{{ selectedCase.initial_message }}</p>
            </div>
            <div>
              <label>必须满足规则</label>
              <div class="tag-list">
                <el-tag v-for="rule in selectedCase.required_rules || []" :key="rule" type="success">{{ rule }}</el-tag>
              </div>
            </div>
            <div>
              <label>禁止触发规则</label>
              <div class="tag-list">
                <el-tag v-for="rule in selectedCase.forbidden_rules || []" :key="rule" type="danger">{{ rule }}</el-tag>
              </div>
            </div>
          </div>
        </template>
      </div>

      <div class="panel conversation-panel">
        <div class="panel-title">
          <h2>多轮对话记录</h2>
          <div class="conversation-title-tags">
            <el-tag v-if="selectedCase" type="info">{{ caseModeLabel(selectedCase.case_mode) }}</el-tag>
            <el-tag v-if="selectedCase" type="info">安全上限 {{ selectedCase.max_turns }} 轮</el-tag>
            <el-tag v-if="result">Run #{{ result.run_id }}</el-tag>
          </div>
        </div>
        <div v-if="selectedCase" class="conversation-target">当前目标：{{ currentGoalText }}</div>
        <div class="conversation-scroll">
          <div v-if="workflowVisible" class="workflow-card">
            <div class="workflow-head">
              <span>Agent 工作流</span>
              <strong>{{ currentRunStage }}</strong>
            </div>
            <div class="workflow-steps">
              <div
                v-for="(step, index) in workflowSteps"
                :key="step.key"
                class="workflow-step"
                :class="{ active: index === currentStageIndex, done: index < currentStageIndex }"
              >
                <span class="stage-dot" />
                <span>
                  <strong>{{ step.label }}</strong>
                  <small>{{ step.description }}</small>
                </span>
              </div>
            </div>
            <div class="progress-track" aria-hidden="true">
              <span :style="{ width: `${progressPercent}%` }" />
            </div>
          </div>

          <div v-if="running && !messages.length && !evaluationError" class="run-progress-state">
            <div class="progress-icon"><Loading /></div>
            <div class="progress-copy">
              <span>评测执行中</span>
              <strong>{{ currentRunStage }}</strong>
              <p>系统正在编排用户模拟器、被测模型、规则评分和 Judge Agent。</p>
            </div>
          </div>

          <div v-if="evaluationError" class="run-error-state">
            <div class="error-icon"><WarningFilled /></div>
            <div>
              <strong>评测失败</strong>
              <p>错误原因：{{ evaluationError }}</p>
              <span>请检查后端服务或模型配置</span>
            </div>
          </div>

          <template v-if="messages.length">
            <div v-if="selectedCase" class="start-card">
              <div class="start-card-head">
                <div>
                  <span>评测起点</span>
                  <strong>{{ selectedCase.name }}</strong>
                </div>
                <div class="start-card-tags">
                  <el-tag type="info">{{ caseModeLabel(selectedCase.case_mode) }}</el-tag>
                  <el-tag type="info">安全上限 {{ selectedCase.max_turns }} 轮</el-tag>
                </div>
              </div>
              <div class="start-grid">
                <div>
                  <label>用户画像</label>
                  <p>{{ selectedCase.user_profile || '暂无用户画像' }}</p>
                </div>
                <div>
                  <label>用户首句回应</label>
                  <p>{{ selectedCase.initial_message || '暂无用户回应' }}</p>
                </div>
                <div>
                  <label>测试目标</label>
                  <p>{{ currentGoalText }}</p>
                </div>
                <div>
                  <label>当前激活规则摘要</label>
                  <div v-if="activeRuleSummary.length" class="tag-list compact-tags">
                    <el-tag v-for="rule in activeRuleSummary" :key="rule" type="info">{{ rule }}</el-tag>
                  </div>
                  <p v-else>开始评测后展示本轮激活规则。</p>
                </div>
              </div>
            </div>
            <ConversationTimeline :messages="messages" />
          </template>

          <div v-else-if="!running && !evaluationError" class="run-empty-state">
            <div class="empty-icon"><VideoPlay /></div>
            <strong>请选择任务和用例后开始评测</strong>
            <p>评测启动后，这里会展示多轮对话、知识召回、规则命中和评分证据。</p>
          </div>
        </div>
      </div>

      <div class="panel score-panel">
        <div class="panel-title"><h2>评分摘要</h2></div>
        <template v-if="scoreSummary">
          <div class="score-head">
            <div class="score-large">{{ scoreSummary.total_score }}</div>
            <div class="score-meta">
              <span>平均响应 {{ scoreSummary.avg_latency_ms }} ms</span>
              <span>总轮数 {{ scoreSummary.total_turns }}</span>
            </div>
          </div>
          <div v-if="streamJudgeResult && !report" class="judge-preview">
            <span>Judge Agent 初评</span>
            <p>{{ streamJudgeResult.reason || 'Judge Agent 已返回阶段性评估。' }}</p>
          </div>
          <ScoreRadar v-if="report" :report="report" />
          <div class="rule-summary">
            <label>命中规则</label>
            <div v-if="matchedRules.length" class="tag-list">
              <el-tag v-for="rule in visibleRules(matchedRules, 5)" :key="rule" type="success">{{ rule }}</el-tag>
              <el-tag v-if="matchedRules.length > 5" type="info">+{{ matchedRules.length - 5 }}</el-tag>
            </div>
            <p v-else class="muted">暂无命中规则</p>
          </div>
          <div class="failure-summary">
            <label>失败规则</label>
            <div v-if="failedRules.length" class="tag-list">
              <el-tag v-for="rule in visibleRules(failedRules, 5)" :key="rule" type="danger">{{ rule }}</el-tag>
              <el-tag v-if="failedRules.length > 5" type="info">+{{ failedRules.length - 5 }}</el-tag>
            </div>
            <p v-else class="muted">暂无失败规则</p>
          </div>
          <div class="pending-summary">
            <label>待完成规则</label>
            <div v-if="pendingRules.length" class="tag-list">
              <el-tag v-for="rule in visibleRules(pendingRules, 5)" :key="rule" type="info">{{ rule }}</el-tag>
              <el-tag v-if="pendingRules.length > 5" type="info">+{{ pendingRules.length - 5 }}</el-tag>
            </div>
            <p v-else class="muted">暂无待完成规则</p>
          </div>
          <el-button
            type="success"
            :icon="View"
            :disabled="!result?.report_id"
            style="width: 100%; margin-top: 14px"
            @click="$router.push(`/reports/${result.report_id}`)"
          >
            查看完整报告
          </el-button>
        </template>
        <div v-else class="score-empty-state">
          <div class="mini-empty-icon"><View /></div>
          <strong>评测完成后显示报告摘要</strong>
          <p>总分、指标分、失败规则和报告入口会在这里汇总。</p>
        </div>
      </div>
    </div>

    <CaseEditor
      v-model="caseEditorVisible"
      :tasks="tasks"
      :case-data="editingCase"
      :default-task-id="taskId"
      @saved="handleCaseSaved"
    />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Edit, Loading, Plus, VideoPlay, View, WarningFilled } from '@element-plus/icons-vue'
import request from '../api/request'
import CaseEditor from '../components/CaseEditor.vue'
import ConversationTimeline from '../components/ConversationTimeline.vue'
import ScoreRadar from '../components/ScoreRadar.vue'

const tasks = ref([])
const cases = ref([])
const taskId = ref(null)
const caseId = ref(null)
const running = ref(false)
const result = ref(null)
const messages = ref([])
const report = ref(null)
const evaluationError = ref('')
const currentStageIndex = ref(0)
const currentStageMessage = ref('')
const streamJudgeResult = ref(null)
const streamDone = ref(false)
const streamMode = ref('')
const modelProvider = ref('mock_fallback')
const caseEditorVisible = ref(false)
const editingCase = ref(null)
const providerOptions = [
  { label: 'mock_fallback（本地兜底，非真实 AI）', value: 'mock_fallback' },
  { label: 'openai_compatible（真实大模型 API）', value: 'openai_compatible' },
  { label: 'custom_endpoint（自定义被测模型接口）', value: 'custom_endpoint' }
]
const workflowSteps = [
  { key: 'scenario', label: 'Scenario Agent', description: '解析当前任务和用例', message: '正在初始化评测任务...' },
  { key: 'knowledge', label: 'Knowledge Retriever', description: '召回相关知识点', message: '正在召回知识库...' },
  { key: 'user', label: 'User Simulator Agent', description: '生成用户发言', message: '用户模拟器 Agent 正在生成用户发言...' },
  { key: 'target', label: 'Target Model', description: '生成被测回复', message: '正在调用被测模型...' },
  { key: 'rules', label: 'Rule Judge', description: '执行硬规则检查', message: '正在进行规则评分...' },
  { key: 'judge', label: 'LLM Judge Agent', description: '生成语义评分', message: 'Judge Agent 正在生成评估意见...' },
  { key: 'report', label: 'Report Agent', description: '生成报告', message: '报告生成中...' }
]
const progressStages = workflowSteps.map((item) => item.message)
let progressTimer = null

const selectedTask = computed(() => tasks.value.find((item) => item.id === taskId.value))
const selectedCase = computed(() => cases.value.find((item) => item.id === caseId.value))
const caseModeLabels = {
  branch: '分支专项用例',
  full_flow: '全流程覆盖用例',
  abnormal_exit: '异常终止用例'
}
const caseModeLabel = (mode) => caseModeLabels[mode] || caseModeLabels.branch
const currentGoalText = computed(() => {
  const goals = selectedCase.value?.expected_goals || []
  return goals.length ? goals.join(' / ') : '暂无目标'
})
const legacyProviderMap = {
  mock_baseline: 'mock_fallback',
  mock_strong: 'mock_fallback'
}
const normalizeProvider = (provider) => legacyProviderMap[provider] || provider || 'mock_fallback'
const displayProvider = (provider) => normalizeProvider(provider)
const modelName = computed(() => normalizeProvider(modelProvider.value))
const currentRunStage = computed(() => currentStageMessage.value || progressStages[currentStageIndex.value] || progressStages[0])
const workflowVisible = computed(() => running.value || streamDone.value || messages.value.length > 0 || Boolean(report.value))
const progressPercent = computed(() =>
  Math.max(12, Math.round(((currentStageIndex.value + 1) / progressStages.length) * 100))
)
const scoreSummary = computed(() => {
  if (report.value) return report.value
  const turnScores = messages.value
    .map((item) => Number(item.rule_score ?? item.score ?? 0))
    .filter((value) => Number.isFinite(value) && value > 0)
  if (!streamJudgeResult.value && !turnScores.length) return null
  const score = Number(streamJudgeResult.value?.score ?? (turnScores.length ? turnScores[turnScores.length - 1] : 0))
  const latencyValues = messages.value
    .map((item) => Number(item.latency_ms ?? item.latency ?? 0))
    .filter((value) => Number.isFinite(value) && value > 0)
  const avgLatency = latencyValues.length
    ? Math.round(latencyValues.reduce((total, value) => total + value, 0) / latencyValues.length)
    : 0
  return {
    total_score: Number.isFinite(score) ? Number(score.toFixed(2)) : 0,
    avg_latency_ms: avgLatency,
    total_turns: messages.value.length
  }
})
const matchedRules = computed(() =>
  Array.from(
    new Set([
      ...(report.value?.matched_rules || report.value?.matchedRules || []),
      ...messages.value.flatMap((item) => item.matched_rules || item.matchedRules || [])
    ])
  )
)
const failedRules = computed(() => {
  if (report.value?.failed_rules || report.value?.failedRules) {
    return report.value.failed_rules || report.value.failedRules || []
  }
  return Array.from(
    new Set(
      messages.value.flatMap((item) => [
        ...(item.missed_rules || item.missedRules || []),
        ...(item.violated_rules || item.violatedRules || [])
      ])
    )
  )
})
const pendingRules = computed(() => {
  const active = report.value?.active_rules || report.value?.activeRules || {}
  return report.value?.pending_rules || report.value?.pendingRules || active.pending_rules || active.pendingRules || []
})
const activeRuleSummary = computed(() => {
  const detail = messages.value[0]?.detail || {}
  const active = detail.active_rules || detail.activeRules || report.value?.active_rules || report.value?.activeRules || {}
  const rules = [
    ...(active.global_rules || active.globalRules || []),
    ...(active.case_rules || active.caseRules || []),
    ...(active.stage_rules || active.stageRules || []),
    ...(active.triggered_rules || active.triggeredRules || [])
  ]
  if (rules.length) return Array.from(new Set(rules)).slice(0, 6)
  return visibleRules([
    ...(selectedCase.value?.required_rules || []),
    ...(selectedCase.value?.forbidden_rules || [])
  ], 4)
})
const isExcelOutboundTask = (task) =>
  task.data_source === 'excel_desensitized' ||
  ['rider_outbound', 'course_platform_outbound'].includes(task.task_type) ||
  ['飞毛腿骑手合同生效外呼评测', '课程直播产品升级外呼评测'].includes(task.name)

const preferExcelTasks = (items) => {
  const excelTasks = items.filter(isExcelOutboundTask)
  return excelTasks.length ? excelTasks : items
}
const caseKey = (item) => `${item.task_id || ''}::${String(item.name || '').trim()}::${String(item.initial_message || '').trim()}`
const dedupeCases = (items = []) => {
  const seen = new Set()
  return items.filter((item) => {
    const key = caseKey(item)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
const visibleRules = (rules, max = 5) => (Array.isArray(rules) ? rules.slice(0, max) : [])
const apiBaseUrl = () => request.defaults.baseURL || ''
const streamSupported = () =>
  typeof fetch === 'function' && typeof ReadableStream !== 'undefined' && typeof TextDecoder !== 'undefined'

const stopProgressTimer = () => {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
}

const startProgressTimer = () => {
  stopProgressTimer()
  currentStageIndex.value = 0
  currentStageMessage.value = ''
  progressTimer = setInterval(() => {
    if (currentStageIndex.value < progressStages.length - 1) {
      currentStageIndex.value += 1
    }
  }, 1200)
}

const setStageByMessage = (message = '') => {
  const text = String(message || '')
  if (text) currentStageMessage.value = text
  const index = workflowSteps.findIndex((step) => text.includes(step.message.replace('...', '')))
  if (index >= 0) {
    currentStageIndex.value = index
    return
  }
  if (text.includes('初始化')) currentStageIndex.value = 0
  else if (text.includes('知识')) currentStageIndex.value = 1
  else if (text.includes('用户模拟器') || text.includes('用户')) currentStageIndex.value = 2
  else if (text.includes('模型')) currentStageIndex.value = 3
  else if (text.includes('规则')) currentStageIndex.value = 4
  else if (text.includes('Judge') || text.includes('评估')) currentStageIndex.value = 5
  else if (text.includes('报告')) currentStageIndex.value = 6
}

const resetEvaluationState = () => {
  messages.value = []
  report.value = null
  result.value = null
  evaluationError.value = ''
  streamJudgeResult.value = null
  streamDone.value = false
  streamMode.value = ''
  currentStageIndex.value = 0
  currentStageMessage.value = ''
}

const loadTasks = async () => {
  tasks.value = preferExcelTasks(await request.get('/api/tasks'))
  if (tasks.value.length) taskId.value = tasks.value[0].id
}

const loadCases = async () => {
  if (!taskId.value) return
  cases.value = dedupeCases(await request.get(`/api/cases?task_id=${taskId.value}`))
  caseId.value = cases.value[0]?.id || null
  messages.value = []
  report.value = null
  result.value = null
  evaluationError.value = ''
  streamJudgeResult.value = null
  streamDone.value = false
  streamMode.value = ''
  currentStageMessage.value = ''
}

const openCreateCase = () => {
  editingCase.value = null
  caseEditorVisible.value = true
}

const openEditCase = () => {
  if (!selectedCase.value) {
    ElMessage.warning('请先选择用例')
    return
  }
  editingCase.value = { ...selectedCase.value }
  caseEditorVisible.value = true
}

const handleCaseSaved = async (savedCase) => {
  taskId.value = savedCase.task_id
  await loadCases()
  caseId.value = savedCase.id
}

const start = async () => {
  if (running.value) return
  if (!taskId.value || !caseId.value || !modelProvider.value) {
    ElMessage.warning('请选择任务、用例和模型 provider')
    return
  }
  running.value = true
  resetEvaluationState()
  try {
    try {
      await startStreamingEvaluation()
    } catch (error) {
      if (error.fallbackToStart) {
        console.warn('[RunConsole] stream unavailable, fallback to /api/runs/start', error.message)
        streamMode.value = 'fallback'
        await startNonStreamingEvaluation()
      } else {
        throw error
      }
    }
  } catch (error) {
    console.error('[RunConsole] evaluation request error', {
      task_id: taskId.value,
      case_id: caseId.value,
      model_provider: modelProvider.value,
      error_message: error.message
    })
    evaluationError.value = error.message || '接口请求失败'
    ElMessage.error(evaluationError.value)
  } finally {
    stopProgressTimer()
    running.value = false
  }
}

const startStreamingEvaluation = async () => {
  if (!streamSupported()) {
    const error = new Error('当前浏览器不支持流式读取')
    error.fallbackToStart = true
    throw error
  }
  streamMode.value = 'stream'
  currentStageIndex.value = 0
  const payload = {
    task_id: taskId.value,
    case_id: caseId.value,
    model_provider: normalizeProvider(modelProvider.value)
  }
  const response = await fetch(`${apiBaseUrl()}/api/runs/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  const contentType = response.headers.get('content-type') || ''
  if (!response.ok || !response.body || !contentType.includes('text/event-stream')) {
    const error = new Error(`流式接口不可用：HTTP ${response.status}`)
    error.fallbackToStart = true
    throw error
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let receivedEvent = false
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split(/\r?\n\r?\n/)
      buffer = parts.pop() || ''
      for (const part of parts) {
        const event = parseSseEvent(part)
        if (!event) continue
        receivedEvent = true
        await handleStreamEvent(event)
        if (event.event === 'error') {
          const error = new Error(event.message || '评测失败')
          error.streamError = true
          throw error
        }
      }
    }
    if (buffer.trim()) {
      const event = parseSseEvent(buffer)
      if (event) {
        receivedEvent = true
        await handleStreamEvent(event)
        if (event.event === 'error') {
          const error = new Error(event.message || '评测失败')
          error.streamError = true
          throw error
        }
      }
    }
  } catch (error) {
    if (!receivedEvent && !error.streamError) error.fallbackToStart = true
    throw error
  }
}

const startNonStreamingEvaluation = async () => {
  startProgressTimer()
  const runResult = await request.post('/api/runs/start', {
    task_id: taskId.value,
    case_id: caseId.value,
    model_provider: normalizeProvider(modelProvider.value)
  })
  result.value = runResult
  if (runResult.success === false) {
    evaluationError.value = runResult.error_message || '接口返回评测失败'
    ElMessage.error(evaluationError.value)
    return
  }
  currentStageIndex.value = progressStages.length - 1
  messages.value = await request.get(`/api/runs/${runResult.run_id}/messages`)
  report.value = await request.get(`/api/reports/${runResult.report_id}`)
  streamDone.value = true
  if (!messages.value.length || !report.value) {
    evaluationError.value = '评测已返回，但对话或报告数据为空'
    return
  }
  ElMessage.success('评测完成')
}

const parseSseEvent = (block) => {
  const data = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.replace(/^data:\s?/, ''))
    .join('\n')
    .trim()
  if (!data) return null
  return JSON.parse(data)
}

const handleStreamEvent = async (event) => {
  if (event.event === 'stage') {
    setStageByMessage(event.message)
    return
  }
  if (event.event === 'user_message') {
    currentStageIndex.value = 2
    upsertStreamTurn(event.turn_index, {
      user_message: event.content || '',
      assistant_message: '',
      detail: { streaming: true }
    })
    return
  }
  if (event.event === 'assistant_start') {
    currentStageIndex.value = 3
    currentStageMessage.value = event.message_phase === 'opening' ? '正在调用被测模型开场...' : '正在调用被测模型...'
    upsertStreamTurn(event.turn_index, {
      assistant_message: '',
      detail: { streaming: true, message_phase: event.message_phase || undefined }
    })
    return
  }
  if (event.event === 'assistant_delta') {
    currentStageIndex.value = 3
    appendAssistantDelta(event.turn_index, event.content || '', event.message_phase)
    return
  }
  if (event.event === 'assistant_done') {
    currentStageIndex.value = 3
    upsertStreamTurn(event.turn_index, {
      assistant_message: event.content || '',
      detail: { streaming: false, message_phase: event.message_phase || undefined }
    })
    return
  }
  if (event.event === 'rule_result') {
    currentStageIndex.value = 4
    currentStageMessage.value = event.summary || '本轮评分完成'
    upsertStreamTurn(event.turn_index, {
      rule_score: event.score ?? 0,
      latency_ms: event.latency_ms ?? 0,
      matched_rules: event.matched_rules || [],
      missed_rules: event.failed_rules || [],
      violated_rules: [],
      detail: {
        message_phase: event.message_phase || undefined,
        retrieved_knowledge: event.retrieved_knowledge || [],
        pending_rules: event.pending_rules || [],
        untriggered_rules: event.untriggered_rules || [],
        not_applicable_rules: event.not_applicable_rules || [],
        rule_lifecycle: event.rule_lifecycle || {},
        deduction_reason: event.deduction_reason || '',
        current_stage: event.current_stage || '',
        memory_state: event.memory_state || {},
        streaming: false
      }
    })
    return
  }
  if (event.event === 'report_generating') {
    setStageByMessage(event.message || '报告生成中...')
    return
  }
  if (event.event === 'judge_result') {
    currentStageIndex.value = 5
    currentStageMessage.value = 'LLM Judge 正在生成评分解释...'
    streamJudgeResult.value = {
      score: Number(event.score || 0),
      reason: event.reason || ''
    }
    return
  }
  if (event.event === 'done') {
    currentStageIndex.value = 6
    currentStageMessage.value = '评测完成'
    streamDone.value = true
    result.value = {
      ...event,
      success: true,
      report_id: event.report_id,
      run_id: event.run_id
    }
    running.value = false
    hydrateStreamReport(event.report_id)
    ElMessage.success('评测完成')
    return
  }
  if (event.event === 'error') {
    evaluationError.value = event.message || '评测失败'
  }
}

const hydrateStreamReport = async (reportId) => {
  if (!reportId) return
  try {
    report.value = await request.get(`/api/reports/${reportId}`)
  } catch (error) {
    console.warn('[RunConsole] report hydration failed after stream done', error.message)
  }
}

const upsertStreamTurn = (turnIndex, patch) => {
  const index = messages.value.findIndex((item) => Number(item.turn_index) === Number(turnIndex))
  const existing = index >= 0 ? messages.value[index] : {
    id: `stream-${turnIndex}`,
    run_id: result.value?.run_id || 0,
    turn_index: turnIndex,
    user_message: '',
    assistant_message: '',
    latency_ms: 0,
    rule_score: 0,
    matched_rules: [],
    missed_rules: [],
    violated_rules: [],
    detail: {}
  }
  const next = {
    ...existing,
    ...patch,
    detail: {
      ...(existing.detail || {}),
      ...(patch.detail || {})
    }
  }
  if (index >= 0) {
    messages.value.splice(index, 1, next)
  } else {
    messages.value.push(next)
  }
}

const appendAssistantDelta = (turnIndex, delta, messagePhase = '') => {
  const index = messages.value.findIndex((item) => Number(item.turn_index) === Number(turnIndex))
  const existing = index >= 0 ? messages.value[index] : null
  upsertStreamTurn(turnIndex, {
    assistant_message: `${existing?.assistant_message || ''}${delta}`,
    detail: { streaming: true, message_phase: messagePhase || undefined }
  })
}

onMounted(async () => {
  await loadTasks()
  await loadCases()
})
</script>

<style scoped>
.config-panel,
.score-panel {
  position: sticky;
  top: 22px;
}

.case-summary {
  display: grid;
  gap: 14px;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.debug-meta {
  display: grid;
  gap: 3px;
  margin: 0 0 12px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}

.provider-note {
  margin: -8px 0 12px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}

.run-stage-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 20px;
  margin-top: 10px;
  color: var(--muted);
  font-size: 12px;
}

.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--cyan-bright);
  box-shadow: 0 0 0 0 rgba(34, 211, 238, 0.34);
  animation: pulse-dot 1.4s ease-out infinite;
}

.conversation-title-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.conversation-target {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
  margin: -4px 0 12px;
}

.case-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin: -4px 0 16px;
}

.case-summary label,
.rule-summary label,
.failure-summary label,
.pending-summary label {
  display: block;
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 6px;
}

.case-summary p {
  margin: 0;
  color: var(--body-text);
}

.conversation-panel {
  min-height: 620px;
}

.conversation-scroll {
  max-height: calc(100vh - 166px);
  min-height: 520px;
  overflow-y: auto;
  padding-right: 4px;
}

.run-progress-state,
.run-error-state,
.run-empty-state,
.score-empty-state,
.workflow-card,
.judge-preview {
  border: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(15, 23, 34, 0.86), rgba(12, 18, 27, 0.78));
  box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.06);
}

.workflow-card {
  display: grid;
  gap: 12px;
  padding: 14px;
  margin-bottom: 14px;
  border-radius: 10px;
}

.workflow-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.workflow-head span,
.judge-preview span {
  color: var(--muted);
  font-size: 12px;
}

.workflow-head strong {
  color: var(--text);
  font-size: 14px;
}

.workflow-steps {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
}

.workflow-step {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--weak);
  font-size: 12px;
}

.workflow-step > span:last-child {
  display: grid;
  gap: 2px;
  overflow: hidden;
}

.workflow-step strong {
  overflow: hidden;
  color: inherit;
  font-size: 12px;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-step small {
  overflow: hidden;
  color: var(--weak);
  font-size: 11px;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-step.active {
  color: var(--text);
}

.workflow-step.active small {
  color: var(--muted);
}

.workflow-step.done {
  color: var(--muted);
}

.workflow-step.active .stage-dot {
  background: var(--cyan-bright);
  box-shadow: 0 0 0 5px rgba(34, 211, 238, 0.12);
}

.workflow-step.done .stage-dot {
  background: var(--cyan);
}

.run-progress-state {
  display: grid;
  gap: 16px;
  padding: 22px;
  border-radius: 10px;
}

.progress-icon,
.empty-icon,
.error-icon,
.mini-empty-icon {
  display: grid;
  place-items: center;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(22, 32, 51, 0.68);
  color: var(--cyan-bright);
}

.progress-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
}

.progress-icon svg {
  width: 23px;
  height: 23px;
  animation: spin 1.1s linear infinite;
}

.progress-copy {
  display: grid;
  gap: 4px;
}

.progress-copy span,
.run-empty-state p,
.score-empty-state p,
.run-error-state span {
  color: var(--muted);
  font-size: 13px;
}

.progress-copy strong,
.run-empty-state strong,
.score-empty-state strong,
.run-error-state strong {
  color: var(--text);
  font-size: 16px;
}

.progress-copy p,
.run-empty-state p,
.score-empty-state p,
.run-error-state p {
  margin: 0;
}

.progress-track {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.16);
}

.progress-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--cyan), var(--blue));
  box-shadow: 0 0 18px rgba(34, 211, 238, 0.22);
  transition: width 0.28s ease;
}

.stage-list {
  display: grid;
  gap: 10px;
}

.stage-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 24px;
  color: var(--weak);
  font-size: 13px;
}

.stage-item.active {
  color: var(--text);
}

.stage-item.done {
  color: var(--muted);
}

.stage-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.5);
}

.stage-item.active .stage-dot {
  background: var(--cyan-bright);
  box-shadow: 0 0 0 5px rgba(34, 211, 238, 0.12);
}

.stage-item.done .stage-dot {
  background: var(--cyan);
}

.run-error-state {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 18px;
  border-radius: 10px;
  border-color: rgba(248, 113, 113, 0.24);
  background: linear-gradient(180deg, rgba(69, 26, 34, 0.34), rgba(15, 23, 34, 0.82));
}

.error-icon {
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  border-radius: 12px;
  color: #fecaca;
  background: rgba(127, 29, 29, 0.28);
  border-color: rgba(248, 113, 113, 0.26);
}

.error-icon svg {
  width: 22px;
  height: 22px;
}

.run-error-state p {
  color: #fecaca;
  margin-top: 4px;
}

.run-empty-state {
  min-height: 420px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 10px;
  padding: 28px;
  border-radius: 10px;
  text-align: center;
}

.empty-icon {
  width: 58px;
  height: 58px;
  border-radius: 16px;
  color: #8fb8c6;
}

.empty-icon svg {
  width: 26px;
  height: 26px;
}

.score-empty-state {
  display: grid;
  justify-items: center;
  gap: 8px;
  padding: 34px 18px;
  border-radius: 10px;
  text-align: center;
}

.judge-preview {
  display: grid;
  gap: 6px;
  padding: 12px;
  margin: 4px 0 10px;
  border-radius: 10px;
}

.judge-preview p {
  margin: 0;
  color: var(--body-text);
  font-size: 13px;
  line-height: 1.6;
}

.mini-empty-icon {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  color: #8fb8c6;
}

.mini-empty-icon svg {
  width: 20px;
  height: 20px;
}

.start-card {
  display: grid;
  gap: 14px;
  padding: 14px;
  margin-bottom: 18px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.42);
}

.start-card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.start-card-head span,
.start-grid label {
  display: block;
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 4px;
}

.start-card-head strong {
  color: var(--body-text);
  font-size: 16px;
}

.start-card-tags,
.compact-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.start-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.start-grid p {
  margin: 0;
  color: var(--body-text);
  line-height: 1.6;
}

.score-head {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  margin-bottom: 8px;
}

.score-meta {
  display: grid;
  gap: 4px;
  color: var(--muted);
  font-size: 13px;
  padding-bottom: 4px;
}

.rule-summary,
.failure-summary,
.pending-summary {
  margin-top: 10px;
}

:deep(.el-loading-mask) {
  background-color: rgba(9, 15, 22, 0.82);
  backdrop-filter: blur(6px);
}

:deep(.el-loading-spinner .path) {
  stroke: var(--cyan-bright);
}

:deep(.el-empty) {
  --el-empty-fill-color-0: rgba(148, 163, 184, 0.1);
  --el-empty-fill-color-1: rgba(148, 163, 184, 0.14);
  --el-empty-fill-color-2: rgba(148, 163, 184, 0.18);
  --el-empty-fill-color-3: rgba(148, 163, 184, 0.12);
  --el-empty-fill-color-4: rgba(148, 163, 184, 0.16);
  --el-empty-fill-color-5: rgba(148, 163, 184, 0.08);
  --el-empty-fill-color-6: rgba(148, 163, 184, 0.12);
  --el-empty-fill-color-7: rgba(148, 163, 184, 0.1);
  --el-empty-fill-color-8: rgba(148, 163, 184, 0.18);
  --el-empty-fill-color-9: rgba(148, 163, 184, 0.22);
  background: transparent;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes pulse-dot {
  0% {
    box-shadow: 0 0 0 0 rgba(34, 211, 238, 0.34);
  }
  70% {
    box-shadow: 0 0 0 8px rgba(34, 211, 238, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(34, 211, 238, 0);
  }
}

@media (max-width: 1100px) {
  .config-panel,
  .score-panel {
    position: static;
  }

  .conversation-scroll {
    max-height: none;
  }

  .start-grid {
    grid-template-columns: 1fr;
  }

  .workflow-steps {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
