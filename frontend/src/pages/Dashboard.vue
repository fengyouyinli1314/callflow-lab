<template>
  <section>
    <div class="page-header">
      <div>
        <h1>数据大屏</h1>
        <p>复杂外呼任务对话模型自动评测平台，聚合展示评测次数、质量得分、响应延迟和常见失败规则。</p>
      </div>
      <div class="toolbar">
        <el-button type="primary" :icon="Operation" @click="$router.push('/batch-runs')">批量评测入口</el-button>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="grid metrics">
      <MetricCard label="任务总数" :value="summary.total_tasks" icon="Document" color="#38bdf8" />
      <MetricCard label="用例总数" :value="summary.total_cases" icon="Tickets" color="#2dd4bf" />
      <MetricCard label="评测次数" :value="summary.total_runs" icon="VideoPlay" color="#7ddc9f" />
      <MetricCard label="批量次数" :value="summary.total_batches" icon="Operation" color="#22d3ee" />
      <MetricCard label="平均得分" :value="summary.avg_score" icon="TrendCharts" color="#f2c94c" />
      <MetricCard label="平均通过率" :value="summary.avg_pass_rate" suffix="%" icon="CircleCheck" color="#7ddc9f" />
      <MetricCard label="平均响应" :value="summary.avg_latency_ms" suffix="ms" icon="Timer" color="#f87171" />
    </div>

    <div class="panel agent-workflow-panel">
      <div class="panel-title">
        <h2>评测工作流</h2>
        <span class="muted">任务解析、知识召回、用户模拟、规则评分和语义评审</span>
      </div>
      <div class="agent-flow">
        <div v-for="(item, index) in agentWorkflow" :key="item.title" class="agent-flow-item">
          <span class="agent-step-index">{{ index + 1 }}</span>
          <strong>{{ item.title }}</strong>
          <p>{{ item.description }}</p>
        </div>
      </div>
    </div>

    <div class="grid two dashboard-charts">
      <div class="panel">
        <div class="panel-title">
          <h2>最近 7 次得分趋势</h2>
          <span class="muted">{{ trendData.length }} 次记录</span>
        </div>
        <div ref="trendRef" class="chart"></div>
      </div>
      <div class="panel">
        <div class="panel-title">
          <h2>失败规则 TOP5</h2>
          <span class="muted">{{ failureData.length }} 项</span>
        </div>
        <el-empty
          v-if="!failureData.length"
          class="empty-chart"
          description="暂无失败规则统计"
        />
        <div v-else ref="failureRef" class="chart"></div>
      </div>
    </div>

    <div class="panel recent-batches">
      <div class="panel-title">
        <h2>最近批量评测结果</h2>
        <span class="muted">{{ recentBatches.length }} 次</span>
      </div>
      <el-empty v-if="!recentBatches.length" description="暂无批量评测结果" />
      <el-table v-else :data="recentBatches">
        <el-table-column prop="batch_id" label="批次" width="90">
          <template #default="{ row }">#{{ row.batch_id }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.status === 'finished' ? 'success' : 'warning'">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total_runs" label="总运行数" width="100" />
        <el-table-column prop="finished_runs" label="已完成" width="90" />
        <el-table-column prop="average_score" label="平均分" width="90" />
        <el-table-column prop="pass_rate" label="通过率" width="90">
          <template #default="{ row }">{{ row.pass_rate }}%</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="180" show-overflow-tooltip />
      </el-table>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { Operation, Refresh } from '@element-plus/icons-vue'
import request from '../api/request'
import MetricCard from '../components/MetricCard.vue'

const summary = ref({
  total_tasks: 0,
  total_cases: 0,
  total_runs: 0,
  avg_score: 0,
  avg_latency_ms: 0,
  avg_pass_rate: 0,
  total_batches: 0,
  failed_rules_top5: [],
  recent_score_trend: [],
  recent_batches: []
})
const trendRef = ref(null)
const failureRef = ref(null)
let trendChart
let failureChart

const trendData = computed(() => summary.value.recent_score_trend || [])
const failureData = computed(() => summary.value.failed_rules_top5 || [])
const recentBatches = computed(() => summary.value.recent_batches || [])
const agentWorkflow = [
  { title: '任务指令解析', description: '解析任务、用例、目标和约束。' },
  { title: '知识召回', description: '召回开场白、流程、常见问题和约束。' },
  { title: '用户模拟器', description: '动态生成被外呼对象的多轮行为。' },
  { title: '被测模型调用', description: '通过所选接入方式生成被测回复。' },
  { title: '规则裁判', description: '检查硬规则、串场和流程覆盖。' },
  { title: '语义评审', description: '给出语义评分、证据和建议。' },
  { title: '报告生成', description: '汇总量化指标和可解释报告。' }
]

const statusLabel = (status) => {
  const labels = {
    running: '运行中',
    finished: '已完成',
    finished_with_errors: '部分失败',
    failed: '失败'
  }
  return labels[status] || status || '-'
}

const drawTrend = () => {
  if (!trendRef.value) return
  if (!trendChart) trendChart = echarts.init(trendRef.value)
  trendChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 38, right: 20, top: 30, bottom: 32 },
    xAxis: {
      type: 'category',
      data: trendData.value.map((item) => `#${item.report_id ?? item.run_id ?? '-'}`),
      axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.28)' } },
      axisTick: { show: false },
      axisLabel: { color: '#94a3b8' }
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: '#94a3b8' },
      splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.14)' } }
    },
    series: [
      {
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 7,
        data: trendData.value.map((item) => Number(item.score ?? 0)),
        lineStyle: { color: '#22d3ee', width: 3 },
        itemStyle: { color: '#2dd4bf' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(34, 211, 238, 0.2)' },
            { offset: 1, color: 'rgba(34, 211, 238, 0.02)' }
          ])
        }
      }
    ]
  })
}

const drawFailure = () => {
  if (!failureData.value.length) {
    failureChart?.dispose()
    failureChart = null
    return
  }
  if (!failureRef.value) return
  if (!failureChart) failureChart = echarts.init(failureRef.value)
  failureChart.setOption({
    tooltip: {},
    grid: { left: 118, right: 24, top: 18, bottom: 28 },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#94a3b8' },
      splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.14)' } }
    },
    yAxis: {
      type: 'category',
      data: failureData.value.map((item) => item.rule_name ?? item.ruleName ?? '-'),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.18)' } },
      axisLabel: { color: '#cbd5e1', width: 108, overflow: 'truncate' }
    },
    series: [
      {
        type: 'bar',
        data: failureData.value.map((item) => Number(item.count ?? 0)),
        barWidth: 16,
        itemStyle: {
          borderRadius: [0, 8, 8, 0],
          color: '#f2c94c'
        }
      }
    ]
  })
}

const draw = () => {
  drawTrend()
  drawFailure()
}

const load = async () => {
  summary.value = await request.get('/api/dashboard/summary')
  await nextTick()
  draw()
}

const resize = () => {
  trendChart?.resize()
  failureChart?.resize()
}

onMounted(load)
window.addEventListener('resize', resize)
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  trendChart?.dispose()
  failureChart?.dispose()
})
</script>

<style scoped>
.agent-workflow-panel,
.dashboard-charts,
.recent-batches {
  margin-top: 16px;
}

.agent-flow {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 10px;
}

.agent-flow-item {
  position: relative;
  display: grid;
  align-content: start;
  gap: 7px;
  min-height: 126px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(15, 23, 34, 0.62);
}

.agent-flow-item:not(:last-child)::after {
  content: "→";
  position: absolute;
  right: -12px;
  top: 18px;
  color: var(--weak);
  font-size: 16px;
}

.agent-step-index {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  color: #07131c;
  background: linear-gradient(135deg, var(--cyan), var(--blue));
  font-size: 12px;
  font-weight: 800;
}

.agent-flow-item strong {
  color: var(--text);
  font-size: 14px;
}

.agent-flow-item p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}

.empty-chart {
  min-height: 320px;
}

@media (max-width: 720px) {
  .agent-flow {
    grid-template-columns: 1fr;
  }

  .agent-flow-item:not(:last-child)::after {
    display: none;
  }
}

@media (min-width: 721px) and (max-width: 1280px) {
  .agent-flow {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .agent-flow-item:not(:last-child)::after {
    display: none;
  }
}
</style>
