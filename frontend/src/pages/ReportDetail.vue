<template>
  <section>
    <div class="page-header">
      <div>
        <h1>评测报告 #{{ report.report_id }}</h1>
        <p>{{ report.explainability?.overall_reason }}</p>
      </div>
      <el-button :icon="Back" @click="$router.push('/runs')">返回评测台</el-button>
    </div>

    <div class="grid two">
      <div class="panel">
        <div class="panel-title"><h2>总分与雷达图</h2></div>
        <div class="status-row">
          <div class="score-large">{{ report.total_score }}</div>
          <div class="muted">平均响应 {{ report.avg_latency_ms }} ms<br />对话轮数 {{ report.total_turns }}</div>
        </div>
        <ScoreRadar :report="report" />
      </div>
      <div class="panel">
        <div class="panel-title"><h2>关键发现</h2></div>
        <div class="tag-list">
          <el-tag v-for="item in report.explainability?.key_findings || []" :key="item" type="info">{{ item }}</el-tag>
        </div>
        <el-divider />
        <p v-for="item in report.suggestions || []" :key="item">{{ item }}</p>
      </div>
    </div>

    <div class="panel" style="margin-top: 16px">
      <div class="panel-title"><h2>指标解释</h2></div>
      <el-table :data="metricRows">
        <el-table-column prop="name" label="指标" width="150" />
        <el-table-column prop="score" label="分数" width="90" />
        <el-table-column prop="deduction_reason" label="扣分原因" min-width="220" />
        <el-table-column prop="evidence_turns" label="证据轮次" width="120">
          <template #default="{ row }">{{ row.evidence_turns?.join('、') }}</template>
        </el-table-column>
        <el-table-column prop="suggestion" label="优化建议" min-width="260" />
      </el-table>
    </div>

    <div class="panel" style="margin-top: 16px">
      <div class="panel-title"><h2>失败案例</h2></div>
      <FailureTable :cases="report.failure_cases || []" />
    </div>

    <div class="panel" style="margin-top: 16px">
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
const report = ref({ explainability: {}, metric_details: {}, suggestions: [], messages: [], failure_cases: [] })
const labels = {
  task_completion: '任务完成度',
  instruction_following: '指令遵循率',
  context_consistency: '上下文一致性',
  safety_compliance: '安全合规性',
  response_quality: '回复质量'
}
const metricRows = computed(() =>
  Object.entries(report.value.metric_details || {}).map(([key, value]) => ({
    key,
    name: labels[key] || key,
    ...value
  }))
)

onMounted(async () => {
  report.value = await request.get(`/api/reports/${route.params.id}`)
})
</script>
