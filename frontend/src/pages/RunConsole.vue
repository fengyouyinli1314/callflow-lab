<template>
  <section>
    <div class="page-header">
      <div>
        <h1>开始评测</h1>
        <p>选择任务、用例和被测模型接入方式后，点击开始评测执行多轮对话、规则评分与报告生成。</p>
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
          <el-form-item label="被测模型接入方式">
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
            离线演示模式仅用于无真实接口时跑通流程；真实大模型接口和自定义模型接口用于接入被测模型。
          </p>
          <div class="debug-meta">
            <span>任务类型：{{ taskTypeLabel(selectedTask?.task_type) }}</span>
            <span>接入方式：{{ displayProvider(result?.provider_used || result?.model_provider || modelProvider) }}</span>
            <span>模型名称：{{ displayRunModelName }}</span>
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
          <div class="quick-check-panel">
            <div class="quick-check-head">
              <strong>单条问答检测</strong>
              <div class="quick-head-actions">
                <span>不生成报告</span>
                <el-button
                  text
                  size="small"
                  :icon="RefreshLeft"
                  :disabled="quickChecking || (!quickCheckText && !quickCheckResult)"
                  @click="resetQuickCheck"
                >
                  清空
                </el-button>
              </div>
            </div>
            <el-input
              v-model="quickCheckText"
              type="textarea"
              :rows="5"
              placeholder="每行一句独立用户发言，例如：&#10;我想退出飞毛腿&#10;标准和低延迟区别在哪？"
            />
            <el-button
              :loading="quickChecking"
              :disabled="quickChecking"
              style="width: 100%; margin-top: 10px"
              @click="runQuickCheck"
            >
              检测单条问答
            </el-button>
          </div>
        </el-form>
      </div>

      <div class="panel conversation-panel">
        <div class="panel-title">
          <h2>多轮对话记录</h2>
          <div class="conversation-title-tags">
            <el-tag v-if="selectedCase" type="info">{{ caseModeLabel(selectedCase.case_mode) }}</el-tag>
            <el-tag v-if="selectedCase" type="info">安全上限 {{ selectedCase.max_turns }} 轮</el-tag>
            <el-tag v-if="result">Run #{{ result.run_id }}</el-tag>
            <el-button
              text
              size="small"
              :icon="RefreshLeft"
              :disabled="running || (!messages.length && !report && !result && !quickCheckResult)"
              @click="resetWorkspace"
            >
              清空记录
            </el-button>
          </div>
        </div>
        <div class="conversation-scroll">
          <div v-if="quickCheckResult" class="quick-check-main">
            <div class="quick-check-main-head">
              <div>
                <span>单条问答检测结果</span>
                <strong>{{ quickCheckResult.total_score }}</strong>
              </div>
              <small>每行用户发言独立评分，不生成正式报告。</small>
            </div>
            <el-table :data="quickCheckRows" class="quick-check-table">
              <el-table-column prop="turn_index" label="序号" width="70" />
              <el-table-column label="用户话" min-width="190">
                <template #default="{ row }">
                  <div class="quick-wrap">{{ row.user_message || '-' }}</div>
                </template>
              </el-table-column>
              <el-table-column label="模型回复" min-width="260">
                <template #default="{ row }">
                  <div class="quick-wrap">{{ row.assistant_message || '-' }}</div>
                </template>
              </el-table-column>
              <el-table-column prop="rule_score" label="单条分" width="90" />
              <el-table-column label="命中 / 缺失" min-width="260">
                <template #default="{ row }">
                  <div class="quick-rule-tags">
                    <el-tag v-for="rule in visibleRules(row.matched_rules, 4)" :key="`m-${row.turn_index}-${rule}`" type="success">
                      {{ rule }}
                    </el-tag>
                    <el-tag v-for="rule in visibleRules([...row.missed_rules, ...row.violated_rules], 4)" :key="`f-${row.turn_index}-${rule}`" type="danger">
                      {{ rule }}
                    </el-tag>
                    <span v-if="!row.matched_rules.length && !row.missed_rules.length && !row.violated_rules.length" class="muted">
                      暂无规则结果
                    </span>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div v-if="workflowVisible" class="workflow-card">
            <div class="workflow-head">
              <span>评测工作流</span>
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
              <p>系统正在编排用户模拟器、被测模型、规则评分和语义评审。</p>
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
            <span>语义评审初评</span>
            <p>{{ streamJudgeResult.reason || '语义评审已返回阶段性评估。' }}</p>
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
import { Edit, Loading, Plus, RefreshLeft, VideoPlay, View, WarningFilled } from '@element-plus/icons-vue'
import request from '../api/request'
import CaseEditor from '../components/CaseEditor.vue'
import ConversationTimeline from '../components/ConversationTimeline.vue'
import ScoreRadar from '../components/ScoreRadar.vue'
import { PROVIDER_OPTIONS, normalizeProvider, providerDisplayName } from '../utils/providerLabels'

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
const quickCheckText = ref('')
const quickChecking = ref(false)
const quickCheckResult = ref(null)
const caseEditorVisible = ref(false)
const editingCase = ref(null)
const providerOptions = PROVIDER_OPTIONS
const workflowSteps = [
  { key: 'scenario', label: '任务解析', description: '解析当前任务和用例', message: '正在初始化评测任务...' },
  { key: 'knowledge', label: '知识召回', description: '召回相关知识点', message: '正在召回知识库...' },
  { key: 'user', label: '用户模拟器', description: '生成用户发言', message: '用户模拟器正在生成用户发言...' },
  { key: 'target', label: '被测模型', description: '生成被测回复', message: '正在调用被测模型...' },
  { key: 'rules', label: '规则评分', description: '执行硬规则检查', message: '正在进行规则评分...' },
  { key: 'judge', label: '语义评审', description: '生成语义评分', message: '正在生成评估意见...' },
  { key: 'report', label: '报告生成', description: '生成报告', message: '报告生成中...' }
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
const displayProvider = (provider) => providerDisplayName(provider)
const modelName = computed(() => providerDisplayName(modelProvider.value))
const displayRunModelName = computed(() => {
  const provider = normalizeProvider(result.value?.provider_used || result.value?.model_provider || modelProvider.value)
  if (provider === 'mock_fallback') return '不适用（内置演示）'
  return result.value?.model_name || modelName.value
})
const taskTypeLabel = (type) => {
  const labels = {
    rider_outbound: '飞毛腿骑手外呼',
    course_platform_outbound: '课程直播外呼',
    generic_outbound: '通用外呼'
  }
  return labels[type] || '未知任务类型'
}
const currentRunStage = computed(() => currentStageMessage.value || progressStages[currentStageIndex.value] || progressStages[0])
const workflowVisible = computed(() => running.value && !evaluationError.value)
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
const quickCheckRows = computed(() => quickCheckResult.value?.turns || [])
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
  else if (text.includes('Judge') || text.includes('评审') || text.includes('评估')) currentStageIndex.value = 5
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

const resetQuickCheck = () => {
  quickCheckText.value = ''
  quickCheckResult.value = null
}

const resetWorkspace = () => {
  if (running.value) return
  resetEvaluationState()
  quickCheckResult.value = null
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

const runQuickCheck = async () => {
  if (!taskId.value || !caseId.value || !modelProvider.value) {
    ElMessage.warning('请先选择任务、用例和被测模型接入方式')
    return
  }
  const userMessages = quickCheckText.value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
  if (!userMessages.length) {
    ElMessage.warning('请至少输入一句用户发言')
    return
  }
  quickChecking.value = true
  try {
    quickCheckResult.value = await request.post('/api/runs/quick-check', {
      task_id: taskId.value,
      case_id: caseId.value,
      model_provider: modelProvider.value,
      user_messages: userMessages,
      include_opening: false
    })
    ElMessage.success('快速检测完成')
  } catch (error) {
    ElMessage.error(error.message || '快速检测失败')
  } finally {
    quickChecking.value = false
  }
}

const start = async () => {
  if (running.value) return
  if (!taskId.value || !caseId.value || !modelProvider.value) {
    ElMessage.warning('请选择任务、用例和被测模型接入方式')
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
    currentStageMessage.value = '语义评审正在生成评分解释...'
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

.quick-check-panel {
  display: grid;
  gap: 10px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.quick-check-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.quick-check-head strong {
  color: var(--text);
  font-size: 14px;
}

.quick-check-head span {
  color: var(--muted);
  font-size: 12px;
}

.quick-head-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.quick-check-result {
  display: grid;
  gap: 10px;
}

.quick-check-main {
  display: grid;
  gap: 12px;
  padding: 16px;
  margin-bottom: 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: linear-gradient(180deg, rgba(15, 23, 34, 0.9), rgba(12, 18, 27, 0.82));
  box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.06);
}

.quick-check-main-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
}

.quick-check-main-head div {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.quick-check-main-head span,
.quick-check-main-head small {
  color: var(--muted);
  font-size: 12px;
}

.quick-check-main-head strong {
  color: var(--cyan);
  font-size: 34px;
  line-height: 1;
}

.quick-check-table :deep(.cell) {
  white-space: normal;
  line-height: 1.45;
}

.quick-wrap {
  white-space: normal;
  word-break: break-word;
  line-height: 1.55;
}

.quick-score {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(15, 23, 34, 0.58);
}

.quick-score span {
  color: var(--muted);
  font-size: 12px;
}

.quick-score strong {
  color: var(--cyan);
  font-size: 22px;
}

.quick-rule-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
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
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
}

.case-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin: -4px 0 16px;
}

.rule-summary label,
.failure-summary label,
.pending-summary label {
  display: block;
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 6px;
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

  .workflow-steps {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
