<template>
  <div ref="chartRef" class="chart"></div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, watch, ref } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  report: { type: Object, default: () => ({}) }
})

const chartRef = ref(null)
let chart

const render = () => {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: {},
    radar: {
      indicator: [
        { name: '任务完成度', max: 100 },
        { name: '指令遵循率', max: 100 },
        { name: '上下文一致性', max: 100 },
        { name: '安全合规性', max: 100 },
        { name: '回复质量', max: 100 }
      ],
      axisName: { color: '#b9c7d4' },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,.24)' } },
      splitArea: { areaStyle: { color: ['rgba(255,255,255,.02)', 'rgba(255,255,255,.04)'] } },
      axisLine: { lineStyle: { color: 'rgba(148,163,184,.24)' } }
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: [
              props.report.task_completion || 0,
              props.report.instruction_following || 0,
              props.report.context_consistency || 0,
              props.report.safety_compliance || 0,
              props.report.response_quality || 0
            ],
            areaStyle: { color: 'rgba(53, 211, 199, .18)' },
            lineStyle: { color: '#35d3c7' },
            itemStyle: { color: '#35d3c7' }
          }
        ]
      }
    ]
  })
}

onMounted(() => nextTick(render))
watch(() => props.report, () => nextTick(render), { deep: true })
window.addEventListener('resize', () => chart?.resize())
onBeforeUnmount(() => chart?.dispose())
</script>
