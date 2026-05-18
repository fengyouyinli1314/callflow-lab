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
        <el-table-column prop="user_behavior_type" label="行为类型" width="110" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button :icon="Edit" text type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button :icon="Delete" text type="danger" @click="deleteCase(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <CaseEditor
      v-model="editorVisible"
      :tasks="tasks"
      :case-data="editingCase"
      :default-task-id="selectedTask"
      @saved="handleEditorSaved"
    />

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
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Delete, Edit, MagicStick, Plus } from '@element-plus/icons-vue'
import request from '../api/request'
import CaseEditor from '../components/CaseEditor.vue'

const tasks = ref([])
const cases = ref([])
const selectedTask = ref(null)
const loading = ref(false)
const editorVisible = ref(false)
const editingCase = ref(null)
const generateDialogVisible = ref(false)
const generating = ref(false)
const savingGenerated = ref(false)
const generatedDrafts = ref([])
const difficultyOptions = ['简单', '中等', '困难']
const behaviorOptions = ['正常配合', '拒绝配合', '情绪不满', '反复追问', '信息缺失', '超范围问题']
const generateForm = reactive({
  task_id: null,
  case_count: 6,
  difficulty_distribution: ['简单', '中等', '困难'],
  user_behavior_types: ['正常配合', '拒绝配合', '情绪不满', '反复追问', '信息缺失', '超范围问题']
})

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
  editingCase.value = null
  editorVisible.value = true
}
const openEdit = (row) => {
  editingCase.value = { ...row }
  editorVisible.value = true
}
const handleEditorSaved = async (payload) => {
  selectedTask.value = payload.task_id
  await loadCases()
}
const deleteCase = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除用例“${row.name}”？`, '删除测试用例', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
    await request.delete(`/api/cases/${row.id}`)
    ElMessage.success('用例已删除')
    await loadCases()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error.message || '删除失败')
    }
  }
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
        user_behavior_type: draft.user_behavior_type || '正常配合',
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
