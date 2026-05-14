<template>
  <section>
    <div class="page-header">
      <div>
        <h1>数据大屏</h1>
        <p>聚合展示评测次数、质量得分、响应延迟和常见失败规则。</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <div class="grid metrics">
      <MetricCard label="任务总数" :value="summary.total_tasks" icon="Document" color="#58a6ff" />
      <MetricCard label="用例总数" :value="summary.total_cases" icon="Tickets" color="#35d3c7" />
      <MetricCard label="评测次数" :value="summary.total_runs" icon="VideoPlay" color="#7ee787" />
      <MetricCard label="平均得分" :value="summary.avg_score" icon="TrendCharts" color="#f5c451" />
      <MetricCard label="平均响应" :value="summary.avg_latency_ms" suffix="ms" icon="Timer" color="#ff6b6b" />
    </div>

    <div class="grid two" style="margin-top: 16px">
      <div class="panel">
        <div class="panel-title"><h2>最近 7 次得分趋势</h2></div>
        <div ref="trendRef" class="chart"></div>
      </div>
      <div class="panel">
        <div class="panel-title"><h2>失败规则 TOP5</h2></div>
        <div ref="failureRef" class="chart"></div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { Refresh } from '@element-plus/icons-vue'
import request from '../api/request'
import MetricCard from '../components/MetricCard.vue'

const summary = ref({
  total_tasks: 0,
  total_cases: 0,
  total_runs: 0,
  avg_score: 0,
  avg_latency_ms: 0,
  failed_rules_top5: [],
  recent_score_trend: []
})
const trendRef = ref(null)
const failureRef = ref(null)
let trendChart
let failureChart

const draw = () => {
  if (trendRef.value) {
    if (!trendChart) trendChart = echarts.init(trendRef.value)
    trendChart.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 36, right: 18, top: 30, bottom: 30 },
      xAxis: {
        type: 'category',
        data: summary.value.recent_score_trend.map((item) => `#${item.report_id}`),
        axisLine: { lineStyle: { color: '#8fa3b8' } }
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        axisLine: { lineStyle: { color: '#8fa3b8' } },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,.18)' } }
      },
      series: [{ type: 'line', smooth: true, data: summary.value.recent_score_trend.map((item) => item.score), color: '#35d3c7', areaStyle: { color: 'rgba(53,211,199,.12)' } }]
    })
  }
  if (failureRef.value) {
    if (!failureChart) failureChart = echarts.init(failureRef.value)
    failureChart.setOption({
      tooltip: {},
      grid: { left: 90, right: 18, top: 24, bottom: 28 },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(148,163,184,.18)' } } },
      yAxis: {
        type: 'category',
        data: summary.value.failed_rules_top5.map((item) => item.rule_name),
        axisLabel: { color: '#b9c7d4', width: 84, overflow: 'truncate' }
      },
      series: [{ type: 'bar', data: summary.value.failed_rules_top5.map((item) => item.count), color: '#f5c451', barWidth: 16 }]
    })
  }
}

const load = async () => {
  summary.value = await request.get('/api/dashboard/summary')
  await nextTick()
  draw()
}

onMounted(load)
window.addEventListener('resize', () => {
  trendChart?.resize()
  failureChart?.resize()
})
onBeforeUnmount(() => {
  trendChart?.dispose()
  failureChart?.dispose()
})
</script>
