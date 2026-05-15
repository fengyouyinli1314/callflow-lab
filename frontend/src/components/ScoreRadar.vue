<template>
  <div ref="chartRef" class="chart"></div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  report: { type: Object, default: () => ({}) }
})

const chartRef = ref(null)
let chart

const metricValues = computed(() => {
  const source = props.report || {}
  return [
    Number(source.task_completion ?? 0),
    Number(source.instruction_following ?? 0),
    Number(source.call_flow_coverage ?? 0),
    Number(source.constraint_compliance ?? source.safety_compliance ?? 0),
    Number(source.context_consistency ?? 0),
    Number(source.response_quality ?? 0)
  ].map((value) => (Number.isFinite(value) ? value : 0))
})

const render = () => {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item' },
    radar: {
      splitNumber: 4,
      radius: '66%',
      center: ['50%', '52%'],
      indicator: [
        { name: '任务完成度', max: 100 },
        { name: '指令遵循率', max: 100 },
        { name: '外呼流程覆盖率', max: 100 },
        { name: '约束遵守率', max: 100 },
        { name: '上下文一致性', max: 100 },
        { name: '回复质量', max: 100 }
      ],
      axisName: {
        color: '#cbd5e1',
        fontSize: 12
      },
      splitLine: {
        lineStyle: { color: 'rgba(148, 163, 184, 0.16)' }
      },
      splitArea: {
        areaStyle: {
          color: ['rgba(18, 26, 36, 0.3)', 'rgba(22, 32, 51, 0.24)']
        }
      },
      axisLine: {
        lineStyle: { color: 'rgba(148, 163, 184, 0.16)' }
      }
    },
    series: [
      {
        type: 'radar',
        symbol: 'circle',
        symbolSize: 5,
        data: [
          {
            value: metricValues.value,
            name: '评分',
            areaStyle: { color: 'rgba(34, 211, 238, 0.18)' },
            lineStyle: { color: '#22d3ee', width: 3 },
            itemStyle: { color: '#2dd4bf' }
          }
        ]
      }
    ]
  })
}

const resize = () => chart?.resize()

onMounted(() => nextTick(render))
watch(metricValues, () => nextTick(render), { deep: true })
window.addEventListener('resize', resize)
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})
</script>
