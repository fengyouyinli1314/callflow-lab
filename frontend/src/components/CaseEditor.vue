<template>
  <el-dialog :model-value="modelValue" :title="dialogTitle" width="820px" @update:model-value="emit('update:modelValue', $event)">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="所属任务" prop="task_id">
        <el-select v-model="form.task_id" style="width: 100%">
          <el-option v-for="task in tasks" :key="task.id" :label="task.name" :value="task.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="用例名称" prop="name">
        <el-input v-model="form.name" maxlength="80" show-word-limit />
      </el-form-item>
      <el-form-item label="用户画像" prop="user_profile">
        <el-input v-model="form.user_profile" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item label="初始问题" prop="initial_message">
        <el-input v-model="form.initial_message" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item label="测试目标" prop="expected_goals_text">
        <el-input v-model="form.expected_goals_text" type="textarea" :rows="3" placeholder="每行一个目标" />
      </el-form-item>
      <div class="grid two">
        <el-form-item label="用户行为类型" prop="user_behavior_type">
          <el-select v-model="form.user_behavior_type" style="width: 100%">
            <el-option v-for="item in behaviorOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="用例模式" prop="case_mode">
          <el-select v-model="form.case_mode" style="width: 100%">
            <el-option v-for="item in caseModeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="最大轮数" prop="max_turns">
          <el-input-number v-model="form.max_turns" :min="1" :max="12" />
        </el-form-item>
      </div>
      <el-form-item label="难度" prop="difficulty">
        <el-segmented v-model="form.difficulty" :options="difficultyOptions" />
      </el-form-item>
      <el-form-item label="必须满足规则" prop="required_rules_text">
        <el-input v-model="form.required_rules_text" type="textarea" :rows="3" placeholder="每行一条规则" />
      </el-form-item>
      <el-form-item label="禁止触发规则" prop="forbidden_rules_text">
        <el-input v-model="form.forbidden_rules_text" type="textarea" :rows="3" placeholder="每行一条规则" />
      </el-form-item>
      <el-form-item label="触发条件" prop="trigger_conditions_text">
        <el-input v-model="form.trigger_conditions_text" type="textarea" :rows="3" placeholder="每行一个触发条件" />
      </el-form-item>
      <el-form-item label="期望结束状态" prop="expected_final_state">
        <el-input v-model="form.expected_final_state" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../api/request'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  tasks: { type: Array, default: () => [] },
  caseData: { type: Object, default: null },
  defaultTaskId: { type: Number, default: null }
})

const emit = defineEmits(['update:modelValue', 'saved'])
const formRef = ref(null)
const saving = ref(false)
const difficultyOptions = ['简单', '中等', '困难']
const behaviorOptions = ['正常配合', '拒绝配合', '情绪不满', '反复追问', '信息缺失', '超范围问题']
const caseModeOptions = [
  { label: '分支专项用例', value: 'branch' },
  { label: '全流程覆盖用例', value: 'full_flow' },
  { label: '异常终止用例', value: 'abnormal_exit' }
]
const form = reactive(emptyForm())
const dialogTitle = computed(() => (props.caseData?.id ? '编辑测试用例' : '新增测试用例'))

const requiredMessage = '请填写该字段'
const rules = {
  task_id: [{ required: true, message: '请选择所属任务', trigger: 'change' }],
  name: [{ required: true, message: requiredMessage, trigger: 'blur' }],
  user_profile: [{ required: true, message: requiredMessage, trigger: 'blur' }],
  initial_message: [{ required: true, message: requiredMessage, trigger: 'blur' }],
  expected_goals_text: [{ required: true, message: '请至少填写一个测试目标', trigger: 'blur' }],
  user_behavior_type: [{ required: true, message: '请选择用户行为类型', trigger: 'change' }],
  case_mode: [{ required: true, message: '请选择用例模式', trigger: 'change' }],
  max_turns: [{ required: true, message: '请选择最大轮数', trigger: 'change' }],
  difficulty: [{ required: true, message: '请选择难度', trigger: 'change' }],
  required_rules_text: [{ required: true, message: '请至少填写一条必须满足规则', trigger: 'blur' }],
  forbidden_rules_text: [{ required: true, message: '请至少填写一条禁止触发规则', trigger: 'blur' }],
  trigger_conditions_text: [{ required: true, message: '请至少填写一个触发条件', trigger: 'blur' }],
  expected_final_state: [{ required: true, message: requiredMessage, trigger: 'blur' }]
}

function emptyForm() {
  return {
    id: null,
    task_id: null,
    name: '',
    user_profile: '',
    initial_message: '',
    expected_goals_text: '',
    required_rules_text: '',
    forbidden_rules_text: '',
    trigger_conditions_text: '',
    expected_final_state: '',
    user_behavior_type: '正常配合',
    case_mode: 'branch',
    difficulty: '中等',
    max_turns: 4,
    data_source: 'manual'
  }
}

function resetForm() {
  const source = props.caseData || {}
  Object.assign(form, {
    id: source.id || null,
    task_id: source.task_id || props.defaultTaskId || props.tasks[0]?.id || null,
    name: source.name || '',
    user_profile: source.user_profile || '',
    initial_message: source.initial_message || '',
    expected_goals_text: toText(source.expected_goals),
    required_rules_text: toText(source.required_rules),
    forbidden_rules_text: toText(source.forbidden_rules),
    trigger_conditions_text: toText(source.trigger_conditions),
    expected_final_state: source.expected_final_state || '',
    user_behavior_type: source.user_behavior_type || '正常配合',
    case_mode: source.case_mode || 'branch',
    difficulty: source.difficulty || '中等',
    max_turns: source.max_turns || 4,
    data_source: source.data_source || 'manual'
  })
  requestAnimationFrame(() => formRef.value?.clearValidate())
}

function toText(value) {
  return Array.isArray(value) ? value.join('\n') : ''
}

function lines(text) {
  return String(text || '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

function payload() {
  return {
    task_id: form.task_id,
    name: form.name.trim(),
    user_profile: form.user_profile.trim(),
    initial_message: form.initial_message.trim(),
    expected_goals: lines(form.expected_goals_text),
    required_rules: lines(form.required_rules_text),
    forbidden_rules: lines(form.forbidden_rules_text),
    trigger_conditions: lines(form.trigger_conditions_text),
    expected_final_state: form.expected_final_state.trim(),
    user_behavior_type: form.user_behavior_type,
    case_mode: form.case_mode || 'branch',
    difficulty: form.difficulty,
    max_turns: form.max_turns,
    data_source: form.data_source || 'manual'
  }
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) {
    ElMessage.warning('请先补齐必填字段')
    return
  }
  saving.value = true
  try {
    const body = payload()
    let saved
    if (form.id) {
      saved = await request.put(`/api/cases/${form.id}`, body)
      ElMessage.success('用例已更新')
    } else {
      saved = await request.post('/api/cases', body)
      ElMessage.success('用例已保存')
    }
    emit('update:modelValue', false)
    emit('saved', saved)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) resetForm()
  }
)

watch(
  () => props.caseData,
  () => {
    if (props.modelValue) resetForm()
  }
)
</script>
