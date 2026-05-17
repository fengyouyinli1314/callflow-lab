<template>
  <section>
    <div class="page-header">
      <div>
        <h1>测试用例</h1>
        <p>维护用户画像、初始问题、期望目标和业务约束规则。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="MagicStick" @click="openGenerate" :disabled="!selectedTask">AI 生成用例</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新增用例</el-button>
      </div>
    </div>

    <div class="panel">
      <div class="toolbar" style="margin-bottom: 14px">
        <el-select v-model="selectedTask" placeholder="按任务筛选" clearable style="width: 280px" @change="loadCases">
          <el-option v-for="task in tasks" :key="task.id" :label="task.name" :value="task.id" />
        </el-select>
      </div>
      <el-table :data="cases" v-loading="loading">
        <el-table-column prop="name" label="用例名称" min-width="170" />
        <el-table-column prop="user_profile" label="用户画像" min-width="220" show-overflow-tooltip />
        <el-table-column prop="initial_message" label="初始问题" min-width="260" show-overflow-tooltip />
        <el-table-column prop="difficulty" label="难度" width="90" />
        <el-table-column prop="max_turns" label="最大轮数" width="100" />
        <el-table-column label="必须满足规则" min-width="260">
          <template #default="{ row }">
            <div class="rule-tags">
              <el-tag v-for="rule in visibleRules(row.required_rules)" :key="rule" type="success">{{ rule }}</el-tag>
              <el-tag v-if="hiddenRuleCount(row.required_rules)" type="info">+{{ hiddenRuleCount(row.required_rules) }}</el-tag>
              <span v-if="!hasRules(row.required_rules)" class="muted">暂无规则</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="禁止触发规则" min-width="260">
          <template #default="{ row }">
            <div class="rule-tags">
              <el-tag v-for="rule in visibleRules(row.forbidden_rules)" :key="rule" type="danger">{{ rule }}</el-tag>
              <el-tag v-if="hiddenRuleCount(row.forbidden_rules)" type="info">+{{ hiddenRuleCount(row.forbidden_rules) }}</el-tag>
              <span v-if="!hasRules(row.forbidden_rules)" class="muted">暂无规则</span>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" title="新增测试用例" width="760px">
      <el-form label-position="top">
        <el-form-item label="所属任务">
          <el-select v-model="form.task_id" style="width: 100%">
            <el-option v-for="task in tasks" :key="task.id" :label="task.name" :value="task.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="用例名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="用户画像"><el-input v-model="form.user_profile" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="初始问题"><el-input v-model="form.initial_message" type="textarea" :rows="2" /></el-form-item>
        <div class="grid two">
          <el-form-item label="最大轮数"><el-input-number v-model="form.max_turns" :min="1" :max="12" /></el-form-item>
          <el-form-item label="难度"><el-select v-model="form.difficulty"><el-option label="简单" value="简单" /><el-option label="中等" value="中等" /><el-option label="困难" value="困难" /></el-select></el-form-item>
        </div>
        <el-form-item label="期望目标"><el-input v-model="goalsText" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="必须满足规则"><el-input v-model="requiredText" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="禁止触发规则"><el-input v-model="forbiddenText" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :icon="Check" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="generateDialogVisible" title="AI 生成测试用例" width="980px">
      <el-form label-position="top">
        <div class="grid two">
          <el-form-item label="所属任务">
            <el-select v-model="generateForm.task_id" style="width: 100%">
              <el-option v-for="task in tasks" :key="task.id" :label="task.name" :value="task.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="生成数量">
            <el-input-number v-model="generateForm.case_count" :min="1" :max="20" />
          </el-form-item>
        </div>
        <el-form-item label="难度分布">
          <el-checkbox-group v-model="generateForm.difficulty_distribution">
            <el-checkbox-button v-for="item in difficultyOptions" :key="item" :label="item" />
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="用户行为类型">
          <el-checkbox-group v-model="generateForm.user_behavior_types">
            <el-checkbox-button v-for="item in behaviorOptions" :key="item" :label="item" />
          </el-checkbox-group>
        </el-form-item>
      </el-form>

      <el-table
        v-if="generatedDrafts.length"
        :data="generatedDrafts"
        v-loading="generating || savingGenerated"
        class="draft-table"
        height="360"
      >
        <el-table-column prop="name" label="用例名称" min-width="160" />
        <el-table-column prop="user_profile" label="用户画像" min-width="150" show-overflow-tooltip />
        <el-table-column prop="initial_message" label="初始问题" min-width="240" show-overflow-tooltip />
        <el-table-column prop="difficulty" label="难度" width="82" />
        <el-table-column prop="max_turns" label="轮数" width="72" />
        <el-table-column label="期望目标" min-width="240">
          <template #default="{ row }">
            <div class="rule-tags">
              <el-tag v-for="goal in visibleRules(row.expected_goals)" :key="goal" type="info">{{ goal }}</el-tag>
              <el-tag v-if="hiddenRuleCount(row.expected_goals)" type="info">+{{ hiddenRuleCount(row.expected_goals) }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="触发条件" min-width="220">
          <template #default="{ row }">
            <div class="rule-tags">
              <el-tag v-for="condition in visibleRules(row.trigger_conditions)" :key="condition">{{ condition }}</el-tag>
              <span v-if="!hasRules(row.trigger_conditions)" class="muted">暂无</span>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <el-button @click="generateDialogVisible = false">取消</el-button>
        <el-button :icon="MagicStick" :loading="generating" @click="generateDrafts">生成草稿</el-button>
        <el-button
          type="primary"
          :icon="Check"
          :disabled="!generatedDrafts.length"
          :loading="savingGenerated"
          @click="saveGeneratedDrafts"
        >
          确认保存
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, MagicStick, Plus } from '@element-plus/icons-vue'
import request from '../api/request'

const tasks = ref([])
const cases = ref([])
const selectedTask = ref(null)
const loading = ref(false)
const dialogVisible = ref(false)
const generateDialogVisible = ref(false)
const generating = ref(false)
const savingGenerated = ref(false)
const generatedDrafts = ref([])
const goalsText = ref('')
const requiredText = ref('')
const forbiddenText = ref('')
const difficultyOptions = ['简单', '中等', '困难']
const behaviorOptions = ['正常配合', '拒绝配合', '情绪不满', '反复追问', '信息缺失', '超范围问题']
const form = reactive({
  task_id: null,
  name: '',
  user_profile: '',
  initial_message: '',
  max_turns: 4,
  difficulty: '中等'
})
const generateForm = reactive({
  task_id: null,
  case_count: 6,
  difficulty_distribution: ['简单', '中等', '困难'],
  user_behavior_types: ['正常配合', '拒绝配合', '情绪不满', '反复追问', '信息缺失', '超范围问题']
})

const lines = (text) => text.split('\n').map((item) => item.trim()).filter(Boolean)
const visibleRules = (rules = []) => (Array.isArray(rules) ? rules.slice(0, 2) : [])
const hiddenRuleCount = (rules = []) => (Array.isArray(rules) && rules.length > 2 ? rules.length - 2 : 0)
const hasRules = (rules = []) => Array.isArray(rules) && rules.length > 0
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
const isExcelOutboundTask = (task) =>
  task.data_source === 'excel_desensitized' ||
  ['rider_outbound', 'course_platform_outbound'].includes(task.task_type) ||
  ['飞毛腿骑手合同生效外呼评测', '课程直播产品升级外呼评测'].includes(task.name)

const preferExcelTasks = (items) => {
  const excelTasks = items.filter(isExcelOutboundTask)
  return excelTasks.length ? excelTasks : items
}

const loadTasks = async () => {
  tasks.value = preferExcelTasks(await request.get('/api/tasks'))
  if (!tasks.value.some((task) => task.id === selectedTask.value)) {
    selectedTask.value = tasks.value[0]?.id || null
  }
}
const loadCases = async () => {
  loading.value = true
  try {
    const data = await request.get(selectedTask.value ? `/api/cases?task_id=${selectedTask.value}` : '/api/cases')
    const taskIds = new Set(tasks.value.map((task) => task.id))
    cases.value = dedupeCases(selectedTask.value ? data : data.filter((item) => taskIds.has(item.task_id)))
  } finally {
    loading.value = false
  }
}
const openCreate = () => {
  Object.assign(form, { task_id: selectedTask.value || tasks.value[0]?.id, name: '', user_profile: '', initial_message: '', max_turns: 4, difficulty: '中等' })
  goalsText.value = ''
  requiredText.value = ''
  forbiddenText.value = ''
  dialogVisible.value = true
}
const save = async () => {
  await request.post('/api/cases', {
    ...form,
    expected_goals: lines(goalsText.value),
    required_rules: lines(requiredText.value),
    forbidden_rules: lines(forbiddenText.value)
  })
  ElMessage.success('已保存')
  dialogVisible.value = false
  selectedTask.value = form.task_id
  loadCases()
}
const openGenerate = () => {
  if (!selectedTask.value && !tasks.value.length) {
    ElMessage.warning('请先选择任务')
    return
  }
  Object.assign(generateForm, {
    task_id: selectedTask.value || tasks.value[0]?.id,
    case_count: 6,
    difficulty_distribution: ['简单', '中等', '困难'],
    user_behavior_types: ['正常配合', '拒绝配合', '情绪不满', '反复追问', '信息缺失', '超范围问题']
  })
  generatedDrafts.value = []
  generateDialogVisible.value = true
}
const generateDrafts = async () => {
  if (!generateForm.task_id) {
    ElMessage.warning('请选择任务')
    return
  }
  if (!generateForm.difficulty_distribution.length || !generateForm.user_behavior_types.length) {
    ElMessage.warning('请至少选择一个难度和一种用户行为')
    return
  }
  generating.value = true
  try {
    generatedDrafts.value = await request.post('/api/cases/generate', {
      task_id: generateForm.task_id,
      case_count: generateForm.case_count,
      difficulty_distribution: generateForm.difficulty_distribution,
      user_behavior_types: generateForm.user_behavior_types
    })
    ElMessage.success(`已生成 ${generatedDrafts.value.length} 条草稿`)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    generating.value = false
  }
}
const saveGeneratedDrafts = async () => {
  if (!generatedDrafts.value.length) return
  savingGenerated.value = true
  try {
    for (const draft of generatedDrafts.value) {
      await request.post('/api/cases', {
        task_id: generateForm.task_id,
        name: draft.name,
        user_profile: draft.user_profile,
        initial_message: draft.initial_message,
        max_turns: draft.max_turns,
        expected_goals: draft.expected_goals || [],
        required_rules: draft.required_rules || [],
        forbidden_rules: draft.forbidden_rules || [],
        difficulty: draft.difficulty || '中等',
        trigger_conditions: draft.trigger_conditions || [],
        expected_final_state: draft.expected_final_state || '',
        data_source: draft.data_source || 'ai_generated'
      })
    }
    ElMessage.success('已确认保存，重复用例会自动复用')
    generateDialogVisible.value = false
    selectedTask.value = generateForm.task_id
    await loadCases()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    savingGenerated.value = false
  }
}

onMounted(async () => {
  await loadTasks()
  await loadCases()
})
</script>

<style scoped>
.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.draft-table {
  margin-top: 8px;
}

.rule-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 58px;
  overflow: hidden;
}

.rule-tags :deep(.el-tag) {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
