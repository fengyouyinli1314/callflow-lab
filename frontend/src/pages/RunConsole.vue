<template>
  <section>
    <div class="page-header">
      <div>
        <h1>开始评测</h1>
        <p>选择任务和用例后自动执行多轮对话、规则评分与报告生成。</p>
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
          <el-button
            type="primary"
            :loading="running"
            :icon="VideoPlay"
            style="width: 100%"
            @click="start"
          >
            开始评测
          </el-button>
        </el-form>

        <template v-if="selectedCase">
          <el-divider />
          <div class="case-summary">
            <div class="summary-row">
              <span>难度</span>
              <el-tag>{{ selectedCase.difficulty }}</el-tag>
            </div>
            <div class="summary-row">
              <span>最大轮数</span>
              <strong>{{ selectedCase.max_turns }} 轮</strong>
            </div>
            <div>
              <label>用户画像</label>
              <p>{{ selectedCase.user_profile }}</p>
            </div>
            <div>
              <label>初始问题</label>
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

      <div class="panel conversation-panel" v-loading="running">
        <div class="panel-title">
          <h2>多轮对话记录</h2>
          <el-tag v-if="result">Run #{{ result.run_id }}</el-tag>
        </div>
        <div class="conversation-scroll">
          <ConversationTimeline :messages="messages" />
        </div>
      </div>

      <div class="panel score-panel">
        <div class="panel-title"><h2>评分摘要</h2></div>
        <template v-if="report">
          <div class="score-head">
            <div class="score-large">{{ report.total_score }}</div>
            <div class="score-meta">
              <span>平均响应 {{ report.avg_latency_ms }} ms</span>
              <span>总轮数 {{ report.total_turns }}</span>
            </div>
          </div>
          <ScoreRadar :report="report" />
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
            <p v-else class="muted">本次评测未触发失败规则</p>
          </div>
          <el-button
            type="success"
            :icon="View"
            style="width: 100%; margin-top: 14px"
            @click="$router.push(`/reports/${report.report_id}`)"
          >
            查看完整报告
          </el-button>
        </template>
        <el-empty v-else description="评测完成后显示报告摘要" />
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoPlay, View } from '@element-plus/icons-vue'
import request from '../api/request'
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

const selectedCase = computed(() => cases.value.find((item) => item.id === caseId.value))
const matchedRules = computed(() =>
  Array.from(new Set(messages.value.flatMap((item) => item.matched_rules || item.matchedRules || [])))
)
const failedRules = computed(() => report.value?.failed_rules || report.value?.failedRules || [])
const isExcelOutboundTask = (task) =>
  task.data_source === 'excel_desensitized' ||
  ['rider_outbound', 'course_platform_outbound'].includes(task.task_type) ||
  ['飞毛腿骑手合同生效外呼评测', '课程直播产品升级外呼评测'].includes(task.name)

const preferExcelTasks = (items) => {
  const excelTasks = items.filter(isExcelOutboundTask)
  return excelTasks.length ? excelTasks : items
}
const visibleRules = (rules, max = 5) => (Array.isArray(rules) ? rules.slice(0, max) : [])

const loadTasks = async () => {
  tasks.value = preferExcelTasks(await request.get('/api/tasks'))
  if (tasks.value.length) taskId.value = tasks.value[0].id
}

const loadCases = async () => {
  if (!taskId.value) return
  cases.value = await request.get(`/api/cases?task_id=${taskId.value}`)
  caseId.value = cases.value[0]?.id || null
  messages.value = []
  report.value = null
  result.value = null
}

const start = async () => {
  if (!taskId.value || !caseId.value) {
    ElMessage.warning('请选择任务和用例')
    return
  }
  running.value = true
  messages.value = []
  report.value = null
  try {
    result.value = await request.post('/api/runs/start', { task_id: taskId.value, case_id: caseId.value })
    messages.value = await request.get(`/api/runs/${result.value.run_id}/messages`)
    report.value = await request.get(`/api/reports/${result.value.report_id}`)
    ElMessage.success('评测完成')
  } finally {
    running.value = false
  }
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

.case-summary label,
.rule-summary label,
.failure-summary label {
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
.failure-summary {
  margin-top: 10px;
}

@media (max-width: 1100px) {
  .config-panel,
  .score-panel {
    position: static;
  }

  .conversation-scroll {
    max-height: none;
  }
}
</style>
