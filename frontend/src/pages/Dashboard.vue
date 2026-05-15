<template>
  <section>
    <div class="page-header">
      <div>
        <h1>数据大屏</h1>
        <p>复杂外呼任务对话评测台，聚合展示评测次数、质量得分、响应延迟和常见失败规则。</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <div class="grid metrics">
      <MetricCard label="任务总数" :value="summary.total_tasks" icon="Document" color="#38bdf8" />
      <MetricCard label="用例总数" :value="summary.total_cases" icon="Tickets" color="#2dd4bf" />
      <MetricCard label="评测次数" :value="summary.total_runs" icon="VideoPlay" color="#7ddc9f" />
      <MetricCard label="平均得分" :value="summary.avg_score" icon="TrendCharts" color="#f2c94c" />
      <MetricCard label="平均响应" :value="summary.avg_latency_ms" suffix="ms" icon="Timer" color="#f87171" />
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
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
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

const trendData = computed(() => summary.value.recent_score_trend || [])
const failureData = computed(() => summary.value.failed_rules_top5 || [])

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
.dashboard-charts {
  margin-top: 16px;
}

.empty-chart {
  min-height: 320px;
}
</style>
