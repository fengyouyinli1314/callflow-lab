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
const loadTasks = async () => {
  tasks.value = await request.get('/api/tasks')
  if (!selectedTask.value && tasks.value.length) selectedTask.value = tasks.value[0].id
}
const loadCases = async () => {
  loading.value = true
  try {
    cases.value = await request.get(selectedTask.value ? `/api/cases?task_id=${selectedTask.value}` : '/api/cases')
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
