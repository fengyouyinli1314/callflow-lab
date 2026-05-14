<template>
  <section>
    <div class="page-header">
      <div>
        <h1>开始评测</h1>
        <p>选择任务和用例后自动执行多轮对话、规则评分与报告生成。</p>
      </div>
    </div>

    <div class="grid run-layout">
      <div class="panel">
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
          <el-button type="primary" :loading="running" :icon="VideoPlay" style="width: 100%" @click="start">开始评测</el-button>
        </el-form>
        <el-divider />
        <div v-if="selectedCase" class="tag-list">
          <el-tag>{{ selectedCase.difficulty }}</el-tag>
          <el-tag type="info">{{ selectedCase.max_turns }} 轮</el-tag>
          <el-tag v-for="rule in selectedCase.required_rules" :key="rule" type="success">{{ rule }}</el-tag>
        </div>
      </div>

      <div class="panel">
        <div class="panel-title">
          <h2>多轮对话记录</h2>
          <el-tag v-if="result">Run #{{ result.run_id }}</el-tag>
        </div>
        <el-empty v-if="!messages.length" description="尚未开始评测" />
        <ConversationTimeline v-else :messages="messages" />
      </div>

      <div class="panel">
        <div class="panel-title"><h2>评分摘要</h2></div>
        <template v-if="report">
          <div class="score-large">{{ report.total_score }}</div>
          <p class="muted">平均响应 {{ report.avg_latency_ms }} ms · 共 {{ report.total_turns }} 轮</p>
          <ScoreRadar :report="report" />
          <div class="tag-list">
            <el-tag v-for="rule in report.failed_rules" :key="rule" type="danger">{{ rule }}</el-tag>
            <el-tag v-if="!report.failed_rules?.length" type="success">无失败规则</el-tag>
          </div>
          <el-button type="success" :icon="View" style="width: 100%; margin-top: 14px" @click="$router.push(`/reports/${report.report_id}`)">查看报告</el-button>
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

const loadTasks = async () => {
  tasks.value = await request.get('/api/tasks')
  if (tasks.value.length) taskId.value = tasks.value[0].id
}
const loadCases = async () => {
  if (!taskId.value) return
  cases.value = await request.get(`/api/cases?task_id=${taskId.value}`)
  caseId.value = cases.value[0]?.id || null
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
