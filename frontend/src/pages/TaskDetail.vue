<template>
  <section>
    <div class="page-header">
      <div>
        <h1>{{ task.name || '任务详情' }}</h1>
        <p>{{ task.description || task.evaluation_goal || '展示脱敏外呼任务指令与关联测试用例。' }}</p>
      </div>
      <el-button :icon="Back" @click="$router.push('/tasks')">返回</el-button>
    </div>

    <div class="grid two task-detail-grid">
      <div class="panel instruction-panel">
        <div class="panel-title">
          <h2>脱敏外呼任务指令</h2>
          <el-tag>{{ sourceLabel(task.data_source) }}</el-tag>
        </div>

        <div class="meta-row">
          <span>场景类型</span>
          <strong>{{ taskTypeLabel(task) }}</strong>
        </div>
        <div class="meta-row">
          <span>数据来源</span>
          <strong>{{ sourceLabel(task.data_source) }}</strong>
        </div>
        <div class="meta-row">
          <span>评测目标</span>
          <p>{{ task.evaluation_goal || task.task_text || '-' }}</p>
        </div>

        <el-collapse v-model="activeSections" class="instruction-collapse">
          <el-collapse-item
            v-for="section in instructionSections"
            :key="section.key"
            :title="section.title"
            :name="section.key"
          >
            <ul v-if="section.type === 'constraints' && parsedConstraints.length" class="constraint-list">
              <li v-for="item in parsedConstraints" :key="item">{{ item }}</li>
            </ul>
            <div v-else-if="section.type === 'steps' && parsedSteps.length" class="steps-list">
              <div v-for="step in parsedSteps" :key="step.step_no || step.title" class="step-card">
                <div class="step-title">
                  <el-tag size="small">Step {{ step.step_no || '-' }}</el-tag>
                  <strong>{{ step.title || '未命名步骤' }}</strong>
                </div>
                <div class="instruction-text compact">{{ step.content || '暂无解析结果' }}</div>
                <div v-if="step.sub_steps?.length" class="sub-steps">
                  <div v-for="sub in step.sub_steps" :key="sub.sub_step_no || sub.title" class="sub-step">
                    <strong>{{ sub.sub_step_no }} {{ sub.title }}</strong>
                    <p>{{ sub.content || '暂无解析结果' }}</p>
                  </div>
                </div>
              </div>
            </div>
            <div v-else-if="section.type === 'policy' && parsedPolicy" class="policy-view">
              <div class="policy-block">
                <h3>reply_rules</h3>
                <div class="policy-grid">
                  <span v-for="(value, key) in parsedPolicy.reply_rules || {}" :key="key">
                    <strong>{{ key }}</strong>
                    <em>{{ value }}</em>
                  </span>
                </div>
              </div>
              <div
                v-for="group in policyGroups"
                :key="group.key"
                class="policy-block"
              >
                <h3>{{ group.key }}</h3>
                <div v-if="group.items.length" class="policy-items">
                  <pre v-for="(item, index) in group.items" :key="`${group.key}-${index}`">{{ formatPolicyItem(item) }}</pre>
                </div>
                <div v-else class="instruction-text compact">暂无执行策略</div>
              </div>
            </div>
            <div v-else class="instruction-text">{{ section.value || '暂无解析结果' }}</div>
          </el-collapse-item>
        </el-collapse>
      </div>

      <div class="panel">
        <div class="panel-title">
          <h2>关联测试用例</h2>
          <span class="muted">{{ cases.length }} 个</span>
        </div>
        <el-table :data="cases" max-height="620">
          <el-table-column prop="name" label="用例名称" min-width="160" show-overflow-tooltip />
          <el-table-column prop="user_profile" label="用户画像" min-width="220" show-overflow-tooltip />
          <el-table-column prop="initial_message" label="初始问题" min-width="220" show-overflow-tooltip />
          <el-table-column prop="difficulty" label="难度" width="90" />
          <el-table-column prop="max_turns" label="轮数" width="80" />
          <el-table-column label="规则摘要" min-width="220">
            <template #default="{ row }">
              <div class="case-rules">
                <el-tag v-for="rule in visibleRules(row.required_rules)" :key="`required-${row.id}-${rule}`" type="success">{{ rule }}</el-tag>
                <el-tag v-if="hiddenRuleCount(row.required_rules)" type="info">+{{ hiddenRuleCount(row.required_rules) }}</el-tag>
                <el-tag v-for="rule in visibleRules(row.forbidden_rules)" :key="`forbidden-${row.id}-${rule}`" type="danger">{{ rule }}</el-tag>
                <span v-if="!hasRules(row)" class="muted">暂无规则</span>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Back } from '@element-plus/icons-vue'
import request from '../api/request'

const route = useRoute()
const router = useRouter()
const task = ref({})
const cases = ref([])
const activeSections = ref(['raw', 'role', 'task', 'opening'])

const instructionSections = computed(() => [
  { key: 'raw', title: '原始指令', value: task.value.instruction_text || task.value.system_instruction || '-' },
  { key: 'role', title: 'Role', value: task.value.role_text || fallbackInstruction('Role') },
  { key: 'task', title: 'Task', value: task.value.task_text || task.value.evaluation_goal || fallbackInstruction('Task') },
  { key: 'opening', title: 'Opening Line', value: task.value.opening_line || fallbackInstruction('Opening Line') },
  { key: 'flow', title: 'Conversation Flow', value: task.value.conversation_flow || task.value.call_flow || fallbackInstruction('Call Flow') || fallbackInstruction('Conversation Flow') },
  { key: 'knowledge', title: 'Knowledge Points', value: task.value.knowledge_points || fallbackInstruction('Knowledge Points') || fallbackInstruction('FAQ') },
  { key: 'constraints', title: 'Constraints', type: 'constraints', value: parsedConstraints.value.join('\n') || fallbackInstruction('Constraints') },
  { key: 'steps', title: 'Steps', type: 'steps', value: parsedSteps.value.length ? 'parsed' : '' },
  { key: 'policy', title: '执行策略 executable_policy', type: 'policy', value: parsedPolicy.value ? 'parsed' : '暂无执行策略' }
])

const parsedConstraints = computed(() => {
  const parsed = parseJson(task.value.constraints)
  if (Array.isArray(parsed)) return parsed.filter(Boolean)
  const text = task.value.constraints || fallbackInstruction('Constraints')
  return String(text || '')
    .split('\n')
    .map((line) => line.replace(/^[-*•]\s*/, '').trim())
    .filter(Boolean)
})

const parsedSteps = computed(() => {
  const parsed = parseJson(task.value.steps)
  return Array.isArray(parsed) ? parsed : []
})

const parsedPolicy = computed(() => {
  const parsed = parseJson(task.value.executable_policy)
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
})

const policyGroups = computed(() => {
  const policy = parsedPolicy.value || {}
  return ['global_priority_rules', 'step_policies', 'branch_policies', 'forbidden_rules', 'memory_fields', 'examples'].map((key) => ({
    key,
    items: Array.isArray(policy[key]) ? policy[key] : []
  }))
})

const parseJson = (value) => {
  if (Array.isArray(value)) return value
  if (!value || typeof value !== 'string') return null
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

const formatPolicyItem = (item) => {
  if (typeof item === 'string') return item
  return JSON.stringify(item, null, 2)
}

const fallbackInstruction = (heading) => {
  const text = task.value.instruction_text || task.value.system_instruction || ''
  if (!text) return ''
  const pattern = new RegExp(`#{1,3}\\s*${heading}[^\\n]*\\n?([\\s\\S]*?)(?=\\n#{1,3}\\s|$)`, 'i')
  const match = text.match(pattern)
  return match?.[1]?.trim() || ''
}

const taskTypeLabel = (item) => {
  const type = item.task_type || ''
  if (type === 'rider_outbound') return '飞毛腿骑手外呼'
  if (type === 'course_platform_outbound') return '课程直播平台外呼'
  return item.target_scenario || '复杂外呼任务'
}

const sourceLabel = (source) => {
  if (source === 'excel_desensitized') return '脱敏 Excel'
  return source || '本地演示'
}
const visibleRules = (rules = []) => (Array.isArray(rules) ? rules.slice(0, 1) : [])
const hiddenRuleCount = (rules = []) => (Array.isArray(rules) && rules.length > 1 ? rules.length - 1 : 0)
const hasRules = (row) => Boolean((row.required_rules || []).length || (row.forbidden_rules || []).length)

onMounted(async () => {
  const detail = await request.get(`/api/tasks/${encodeURIComponent(route.params.id)}`)
  task.value = detail
  const taskId = detail.id || route.params.id
  if (String(route.params.id) !== String(taskId)) {
    router.replace(`/tasks/${taskId}`)
  }
  cases.value = await request.get(`/api/cases?task_id=${taskId}`)
})
</script>

<style scoped>
.task-detail-grid {
  align-items: start;
}

.instruction-panel {
  min-width: 0;
}

.meta-row {
  display: grid;
  grid-template-columns: 92px 1fr;
  gap: 12px;
  align-items: start;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}

.meta-row span {
  color: var(--muted);
}

.meta-row strong,
.meta-row p {
  margin: 0;
  color: var(--body-text);
}

.instruction-collapse {
  margin-top: 14px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

.instruction-collapse :deep(.el-collapse-item__header),
.instruction-collapse :deep(.el-collapse-item__wrap),
.instruction-collapse :deep(.el-collapse-item__content) {
  background: rgba(15, 23, 42, 0.58);
  color: var(--body-text);
  border-bottom-color: var(--line);
}

.instruction-collapse :deep(.el-collapse-item__header) {
  padding: 0 12px;
  font-weight: 700;
}

.instruction-collapse :deep(.el-collapse-item__content) {
  padding: 12px;
}

.instruction-text {
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
  color: var(--body-text);
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(9, 15, 22, 0.72);
}

.instruction-text.compact {
  max-height: 160px;
  margin-top: 8px;
}

.constraint-list {
  margin: 0;
  padding: 12px 12px 12px 30px;
  line-height: 1.8;
  color: var(--body-text);
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(9, 15, 22, 0.72);
}

.steps-list {
  display: grid;
  gap: 10px;
}

.step-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.02);
}

.step-title {
  display: flex;
  gap: 8px;
  align-items: center;
}

.sub-steps {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.sub-step {
  border-left: 2px solid var(--line);
  padding-left: 10px;
}

.sub-step p {
  margin: 6px 0 0;
  white-space: pre-wrap;
  color: var(--body-text);
}

.policy-view {
  display: grid;
  gap: 12px;
}

.policy-block {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  background: rgba(9, 15, 22, 0.72);
}

.policy-block h3 {
  margin: 0 0 10px;
  font-size: 14px;
  color: var(--body-text);
}

.policy-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 8px;
}

.policy-grid span,
.policy-items pre {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.72);
}

.policy-grid span {
  display: grid;
  gap: 4px;
  padding: 10px;
}

.policy-grid strong {
  color: var(--muted);
}

.policy-grid em {
  font-style: normal;
  color: var(--body-text);
}

.policy-items {
  display: grid;
  gap: 8px;
}

.policy-items pre {
  max-height: 220px;
  margin: 0;
  overflow: auto;
  padding: 10px;
  white-space: pre-wrap;
  color: var(--body-text);
  font-family: inherit;
  line-height: 1.6;
}

.case-rules {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  max-height: 58px;
  overflow: hidden;
}

.case-rules :deep(.el-tag) {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
