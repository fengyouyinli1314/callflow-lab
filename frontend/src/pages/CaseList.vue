<template>
  <section>
    <div class="page-header">
      <div>
        <h1>测试用例</h1>
        <p>维护用户画像、初始问题、期望目标和业务约束规则。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新增用例</el-button>
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
            </div>
          </template>
        </el-table-column>
        <el-table-column label="禁止触发规则" min-width="260">
          <template #default="{ row }">
            <div class="rule-tags">
              <el-tag v-for="rule in visibleRules(row.forbidden_rules)" :key="rule" type="danger">{{ rule }}</el-tag>
              <el-tag v-if="hiddenRuleCount(row.forbidden_rules)" type="info">+{{ hiddenRuleCount(row.forbidden_rules) }}</el-tag>
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
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Plus } from '@element-plus/icons-vue'
import request from '../api/request'

const tasks = ref([])
const cases = ref([])
const selectedTask = ref(null)
const loading = ref(false)
const dialogVisible = ref(false)
const goalsText = ref('')
const requiredText = ref('')
const forbiddenText = ref('')
const form = reactive({
  task_id: null,
  name: '',
  user_profile: '',
  initial_message: '',
  max_turns: 4,
  difficulty: '中等'
})

const lines = (text) => text.split('\n').map((item) => item.trim()).filter(Boolean)
const visibleRules = (rules = []) => (Array.isArray(rules) ? rules.slice(0, 2) : [])
const hiddenRuleCount = (rules = []) => (Array.isArray(rules) && rules.length > 2 ? rules.length - 2 : 0)
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
    cases.value = selectedTask.value ? data : data.filter((item) => taskIds.has(item.task_id))
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

onMounted(async () => {
  await loadTasks()
  await loadCases()
})
</script>

<style scoped>
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
