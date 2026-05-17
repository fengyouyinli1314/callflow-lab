<template>
  <section>
    <div class="page-header">
      <div>
        <h1>批量评测</h1>
        <p>按任务、用例范围和模型 provider 批量执行评测，汇总平均分、通过率和常见失败规则。</p>
      </div>
    </div>

    <div class="grid two">
      <div class="panel">
        <div class="panel-title"><h2>批量配置</h2></div>
        <el-form label-position="top">
          <el-form-item label="选择任务">
            <el-select v-model="selectedTaskIds" multiple collapse-tags collapse-tags-tooltip style="width: 100%" @change="loadCases">
              <el-option v-for="task in tasks" :key="task.id" :label="task.name" :value="task.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="测试用例范围">
            <el-select
              v-model="selectedCaseIds"
              multiple
              clearable
              collapse-tags
              collapse-tags-tooltip
              placeholder="不选表示使用所选任务下全部用例"
              style="width: 100%"
            >
              <el-option v-for="item in caseOptions" :key="item.id" :label="item.label" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="被测模型 provider">
            <el-select v-model="modelProviders" multiple collapse-tags style="width: 100%">
              <el-option v-for="provider in providerOptions" :key="provider" :label="provider" :value="provider" />
            </el-select>
          </el-form-item>
          <el-form-item label="重复次数">
            <el-input-number v-model="repeatTimes" :min="1" :max="10" />
          </el-form-item>
          <el-button type="primary" :icon="VideoPlay" :loading="running" style="width: 100%" @click="startBatch">
            开始批量评测
          </el-button>
        </el-form>
      </div>

      <div class="panel">
        <div class="panel-title">
          <h2>运行进度</h2>
          <el-tag v-if="summary">Batch #{{ summary.batch_id }}</el-tag>
        </div>
        <template v-if="summary">
          <el-progress :percentage="progressPercent" :stroke-width="12" />
          <div class="batch-status-grid">
            <div><span>总运行数</span><strong>{{ summary.total_runs }}</strong></div>
            <div><span>已完成</span><strong>{{ summary.finished_runs }}</strong></div>
            <div><span>失败</span><strong>{{ summary.failed_runs }}</strong></div>
            <div><span>状态</span><strong>{{ statusLabel(summary.status) }}</strong></div>
          </div>
        </template>
        <el-empty v-else description="批量评测完成后显示进度和汇总" />
      </div>
    </div>

    <template v-if="summary">
      <div class="grid metrics batch-metrics">
        <MetricCard label="平均分" :value="summary.average_score" icon="TrendCharts" color="#2dd4bf" />
        <MetricCard label="通过率" :value="summary.pass_rate" suffix="%" icon="CircleCheck" color="#7ddc9f" />
        <MetricCard label="平均响应" :value="summary.average_latency_ms" suffix="ms" icon="Timer" color="#38bdf8" />
        <MetricCard label="报告数" :value="reportList.length" icon="Document" color="#f2c94c" />
      </div>

      <div class="grid two batch-panels">
        <div class="panel">
          <div class="panel-title">
            <h2>失败规则 TOP5</h2>
            <span class="muted">{{ failedRulesTop5.length }} 项</span>
          </div>
          <el-empty v-if="!failedRulesTop5.length" description="暂无失败规则" />
          <el-table v-else :data="failedRulesTop5">
            <el-table-column prop="rule_name" label="规则" min-width="220" show-overflow-tooltip />
            <el-table-column prop="count" label="次数" width="90" />
          </el-table>
        </div>

        <div v-if="modelSummary.length > 1" class="panel">
          <div class="panel-title">
            <h2>模型 provider 对比</h2>
            <span class="muted">最佳：{{ summary.best_model_provider || '-' }}</span>
          </div>
          <div ref="modelChartRef" class="chart"></div>
        </div>

        <div v-else class="panel">
          <div class="panel-title"><h2>任务得分汇总</h2></div>
          <el-empty v-if="!taskScoreSummary.length" description="暂无任务汇总" />
          <el-table v-else :data="taskScoreSummary">
            <el-table-column prop="task_name" label="任务" min-width="220" show-overflow-tooltip />
            <el-table-column prop="average_score" label="平均分" width="100" />
            <el-table-column prop="pass_rate" label="通过率" width="100">
              <template #default="{ row }">{{ row.pass_rate }}%</template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <div class="panel batch-panels">
        <div class="panel-title">
          <h2>报告列表</h2>
          <span class="muted">{{ reportList.length }} 条</span>
        </div>
        <el-table :data="reportList" max-height="520">
          <el-table-column prop="task_name" label="任务" min-width="210" show-overflow-tooltip />
          <el-table-column prop="case_name" label="用例" min-width="190" show-overflow-tooltip />
          <el-table-column prop="model_provider" label="provider" width="150" />
          <el-table-column prop="repeat_index" label="重复" width="80" />
          <el-table-column prop="total_score" label="得分" width="90" />
          <el-table-column prop="avg_latency_ms" label="平均响应" width="110" />
          <el-table-column prop="status" label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="row.status === 'finished' ? 'success' : 'danger'">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button
                size="small"
                :icon="View"
                :disabled="!row.report_id"
                @click="$router.push(`/reports/${row.report_id}`)"
              >
                查看报告
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { VideoPlay, View } from '@element-plus/icons-vue'
import request from '../api/request'
import MetricCard from '../components/MetricCard.vue'

const tasks = ref([])
const cases = ref([])
const selectedTaskIds = ref([])
const selectedCaseIds = ref([])
const modelProviders = ref(['mock_fallback'])
const repeatTimes = ref(1)
const running = ref(false)
const batch = ref(null)
const summary = ref(null)
const modelChartRef = ref(null)
let modelChart

const providerOptions = ['mock_fallback', 'openai_compatible', 'custom_endpoint']

const taskNameById = computed(() => Object.fromEntries(tasks.value.map((task) => [task.id, task.name])))
const caseOptions = computed(() =>
  cases.value.map((item) => ({
    ...item,
    label: `${taskNameById.value[item.task_id] || '任务'} / ${item.name}`
  }))
)
const progressPercent = computed(() => {
  if (!summary.value?.total_runs) return 0
  return Math.round(((summary.value.finished_runs + summary.value.failed_runs) / summary.value.total_runs) * 100)
})
const failedRulesTop5 = computed(() => summary.value?.failed_rule_top5 || [])
const reportList = computed(() => summary.value?.report_list || [])
const modelSummary = computed(() => summary.value?.model_score_summary || [])
const taskScoreSummary = computed(() => summary.value?.task_score_summary || [])

const isExcelOutboundTask = (task) =>
  task.data_source === 'excel_desensitized' ||
  ['rider_outbound', 'course_platform_outbound'].includes(task.task_type) ||
  ['飞毛腿骑手合同生效外呼评测', '课程直播产品升级外呼评测'].includes(task.name)

const preferExcelTasks = (items) => {
  const excelTasks = items.filter(isExcelOutboundTask)
  return excelTasks.length ? excelTasks : items
}

const statusLabel = (status) => {
  const labels = {
    running: '运行中',
    finished: '已完成',
    finished_with_errors: '部分失败',
    failed: '失败',
    pending: '等待中'
  }
  return labels[status] || status || '-'
}

const loadTasks = async () => {
  tasks.value = preferExcelTasks(await request.get('/api/tasks'))
  selectedTaskIds.value = tasks.value.slice(0, 2).map((task) => task.id)
  await loadCases()
}

const loadCases = async () => {
  selectedCaseIds.value = []
  if (!selectedTaskIds.value.length) {
    cases.value = []
    return
  }
  const groups = await Promise.all(
    selectedTaskIds.value.map((taskId) => request.get(`/api/cases?task_id=${taskId}`))
  )
  cases.value = groups.flat()
}

const startBatch = async () => {
  if (!selectedTaskIds.value.length) {
    ElMessage.warning('请选择任务')
    return
  }
  if (!modelProviders.value.length) {
    ElMessage.warning('请选择被测模型 provider')
    return
  }
  running.value = true
  try {
    batch.value = await request.post('/api/batch-runs/start', {
      task_ids: selectedTaskIds.value,
      case_ids: selectedCaseIds.value,
      model_providers: modelProviders.value,
      repeat_times: repeatTimes.value
    })
    summary.value = batch.value.summary || (await request.get(`/api/batch-runs/${batch.value.batch_id}/summary`))
    await nextTick()
    renderModelChart()
    ElMessage.success('批量评测完成')
  } finally {
    running.value = false
  }
}

const renderModelChart = () => {
  if (modelSummary.value.length <= 1) {
    modelChart?.dispose()
    modelChart = null
    return
  }
  if (!modelChartRef.value) return
  if (!modelChart) modelChart = echarts.init(modelChartRef.value)
  modelChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 42, right: 18, top: 30, bottom: 36 },
    xAxis: {
      type: 'category',
      data: modelSummary.value.map((item) => item.model_provider),
      axisLabel: { color: '#94a3b8' },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.2)' } }
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
        type: 'bar',
        data: modelSummary.value.map((item) => Number(item.average_score || 0)),
        barWidth: 26,
        itemStyle: {
          borderRadius: [8, 8, 0, 0],
          color: '#22d3ee'
        }
      }
    ]
  })
}

const resize = () => modelChart?.resize()

watch(modelSummary, () => nextTick(renderModelChart), { deep: true })
onMounted(loadTasks)
window.addEventListener('resize', resize)
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  modelChart?.dispose()
})
</script>

<style scoped>
.batch-metrics,
.batch-panels {
  margin-top: 16px;
}

.batch-status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(100px, 1fr));
  gap: 10px;
  margin-top: 18px;
}

.batch-status-grid div {
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(22, 32, 51, 0.48);
}

.batch-status-grid span {
  display: block;
  color: var(--muted);
  font-size: 12px;
}

.batch-status-grid strong {
  display: block;
  margin-top: 4px;
  color: var(--text);
  font-size: 18px;
}

@media (max-width: 720px) {
  .batch-status-grid {
    grid-template-columns: repeat(2, minmax(100px, 1fr));
  }
}
</style>
