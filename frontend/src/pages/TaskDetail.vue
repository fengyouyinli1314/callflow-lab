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
            <div class="instruction-text">{{ section.value || '暂无内容' }}</div>
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
          <el-table-column prop="difficulty" label="难度" width="90" />
          <el-table-column prop="max_turns" label="轮数" width="80" />
        </el-table>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Back } from '@element-plus/icons-vue'
import request from '../api/request'

const route = useRoute()
const task = ref({})
const cases = ref([])
const activeSections = ref(['role', 'task', 'opening'])

const instructionSections = computed(() => [
  { key: 'role', title: 'Role', value: task.value.role_text || fallbackInstruction('Role') },
  { key: 'task', title: 'Task', value: task.value.task_text || task.value.evaluation_goal || fallbackInstruction('Task') },
  { key: 'opening', title: 'Opening Line', value: task.value.opening_line || fallbackInstruction('Opening Line') },
  { key: 'flow', title: 'Call Flow', value: task.value.call_flow || fallbackInstruction('Call Flow') || fallbackInstruction('Conversation Flow') },
  { key: 'knowledge', title: 'Knowledge Points', value: task.value.knowledge_points || fallbackInstruction('Knowledge Points') || fallbackInstruction('FAQ') },
  { key: 'constraints', title: 'Constraints', value: task.value.constraints || fallbackInstruction('Constraints') },
  { key: 'raw', title: '完整原始指令', value: task.value.instruction_text || task.value.system_instruction || '-' }
])

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

onMounted(async () => {
  task.value = await request.get(`/api/tasks/${route.params.id}`)
  cases.value = await request.get(`/api/cases?task_id=${route.params.id}`)
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
}

.instruction-text {
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
  color: var(--body-text);
  padding-right: 6px;
}
</style>
