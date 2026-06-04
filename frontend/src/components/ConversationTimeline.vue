<template>
  <el-empty
    v-if="!turns.length"
    description="请在左侧选择任务和用例后开始评测"
  />
  <div v-else class="conversation-chat">
    <section v-for="item in turns" :key="item.key" class="turn-block">
      <div class="turn-index">{{ item.turnLabel }}</div>

      <div v-if="!item.isOpening" class="message-row user-row">
        <div class="message-stack">
          <div class="message-name user-name">用户模拟器</div>
          <div class="bubble user-bubble">{{ item.userMessage || '暂无用户发言' }}</div>
          <div v-if="props.showUserDebug && (item.userIntent || item.goalProgress || item.shouldContinue !== undefined)" class="state-row user-state-row">
            <el-tag v-if="item.userEvent" type="warning">事件：{{ item.userEvent }}</el-tag>
            <el-tag v-if="item.userIntent" type="info">意图：{{ item.userIntent }}</el-tag>
            <el-tag v-if="item.goalProgress" type="info">进度：{{ item.goalProgress }}</el-tag>
            <el-tag v-if="item.shouldContinue !== undefined" :type="item.shouldContinue === false ? 'warning' : 'info'">
              {{ item.shouldContinue === false ? '不继续' : '继续' }}
            </el-tag>
          </div>
          <el-collapse v-if="props.showUserDebug && item.debugStateTags.length" class="debug-collapse">
            <el-collapse-item title="调试信息" :name="`debug-${item.key}`">
              <p class="debug-note">模拟状态，仅用于生成下一轮用户，不参与评分。</p>
              <div class="state-row user-state-row">
                <el-tag v-for="tag in item.debugStateTags" :key="`debug-${item.key}-${tag}`" type="info">{{ tag }}</el-tag>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
        <div class="avatar user">U</div>
      </div>

      <div class="message-row assistant-row">
        <div class="avatar model">M</div>
        <div class="message-stack">
          <div class="message-name">{{ item.isOpening ? '被测模型开场' : '被测模型' }}</div>
          <div class="bubble assistant-bubble" :class="{ 'is-streaming': item.isStreaming }">
            {{ item.assistantMessage || (item.isStreaming ? '' : '暂无回复内容') }}
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  showUserDebug: { type: Boolean, default: false }
})

const toArray = (value) => {
  if (Array.isArray(value)) return value.filter(Boolean)
  if (typeof value === 'string' && value.trim()) return [value]
  return []
}

const pickMessage = (item, primaryKey, fallbackRole) => {
  if (item?.[primaryKey]) return item[primaryKey]
  if (item?.[fallbackRole]?.content) return item[fallbackRole].content
  if (item?.[fallbackRole]?.message) return item[fallbackRole].message
  if ((item?.role === fallbackRole || item?.sender === fallbackRole) && (item?.content || item?.message)) {
    return item.content || item.message
  }
  return ''
}

const buildDebugStateTags = (detail = {}) => {
  const state = detail.user_state || detail.userState || {}
  const tags = []
  if (state.emotion_level !== undefined && state.emotion_level !== null) tags.push(`情绪 ${state.emotion_level}`)
  if (state.patience !== undefined && state.patience !== null) tags.push(`耐心 ${state.patience}`)
  if (state.current_intent && state.current_intent !== detail.user_intent) tags.push(`状态 ${state.current_intent}`)
  return tags
}

const buildMemoryTags = (detail = {}) => {
  const memory = detail.memory_state || detail.memoryState || {}
  const flow = memory.flow_memory || memory.flowMemory || {}
  const branch = memory.user_branch_memory || memory.userBranchMemory || {}
  const unfinished = memory.unfinished_items_memory || memory.unfinishedItemsMemory || {}
  const performance = memory.model_performance_memory || memory.modelPerformanceMemory || {}
  const tags = []
  if (memory.user_event) tags.push(`事件 ${memory.user_event}`)
  if (memory.current_step) tags.push(`当前 ${memory.current_step}`)
  if (memory.interrupted) tags.push('已打断')
  if (memory.pending_return_step) tags.push(`回到 ${memory.pending_return_step}`)
  if (memory.next_best_action) tags.push(`动作 ${memory.next_best_action}`)
  if (flow.current_stage) tags.push(`阶段 ${flow.current_stage}`)
  if (Array.isArray(flow.covered_steps)) tags.push(`已覆盖 ${flow.covered_steps.length}`)
  if (Array.isArray(flow.pending_steps)) tags.push(`待覆盖 ${flow.pending_steps.length}`)
  if (unfinished.next_suggested_step) tags.push(`下一步 ${unfinished.next_suggested_step}`)
  if (branch.awareness) tags.push(`知情 ${branch.awareness}`)
  if (branch.publish_method) tags.push(`发布 ${branch.publish_method}`)
  if (branch.busy) tags.push('用户忙')
  if (branch.driving) tags.push('用户开车')
  if (Array.isArray(performance.interrupted_turns) && performance.interrupted_turns.length) {
    tags.push(`打断 ${performance.interrupted_turns.length}`)
  }
  return tags.slice(0, 12)
}
const knowledgeTypeLabel = (type) => {
  const labels = {
    opening: 'Opening',
    flow: 'Flow',
    faq: 'FAQ',
    constraint: 'Constraint'
  }
  return labels[type] || type || 'Knowledge'
}

const turns = computed(() =>
  props.messages.map((item, index) => {
    const score = Number(item.rule_score ?? item.turn_score ?? item.score ?? 0)
    const detail = item.detail || item.metadata || {}
    const missedRules = toArray(item.missed_rules ?? item.missedRules)
    const violatedRules = toArray(item.violated_rules ?? item.violatedRules)
    const turnIndex = item.turn_index ?? item.turnIndex ?? index + 1
    const isOpening = detail.message_phase === 'opening' || (Number(turnIndex) === 0 && !pickMessage(item, 'user_message', 'user'))
    const knowledgeRefs = toArray(detail.retrieved_knowledge ?? detail.retrievedKnowledge).map((chunk, chunkIndex) => ({
      key: `${chunk.title || chunkIndex}-${chunk.source || chunkIndex}`,
      title: chunk.title || '未命名知识',
      type: knowledgeTypeLabel(chunk.chunk_type || chunk.chunkType),
      source: chunk.source || '',
      content: chunk.content || ''
    }))
    const memory = detail.memory_state || detail.memoryState || {}
    return {
      key: item.id || `${item.run_id || 'turn'}-${item.turn_index || index + 1}`,
      turnIndex,
      turnLabel: isOpening ? '第 0 轮 · 被测模型开场' : `第 ${turnIndex} 轮 · 用户回应与模型回复`,
      isOpening,
      userMessage: pickMessage(item, 'user_message', 'user'),
      assistantMessage:
        pickMessage(item, 'assistant_message', 'assistant') ||
        pickMessage(item, 'model_message', 'model'),
      latencyMs: Number(item.latency_ms ?? item.latency ?? 0).toFixed(0),
      score: Number.isFinite(score) ? Number(score.toFixed(1)) : 0,
      currentStage: detail.current_stage || detail.currentStage || '',
      userIntent: detail.user_intent || detail.userIntent || '',
      userEvent: memory.user_event || (detail.user_metadata || detail.userMetadata || {}).user_event || '',
      goalProgress: (detail.user_state || detail.userState || {}).goal_progress || (detail.user_state || detail.userState || {}).goalProgress || '',
      debugStateTags: buildDebugStateTags(detail),
      memoryTags: buildMemoryTags(detail),
      shouldContinue: detail.should_continue ?? detail.shouldContinue,
      knowledgeRefs,
      deductionReason: detail.deduction_reason || detail.deductionReason || '',
      showDeductionReason: Boolean(detail.deduction_reason || detail.deductionReason) && score < 100,
      isStreaming: Boolean(detail.streaming)
    }
  })
)

const scoreType = (score) => {
  if (score >= 90) return 'success'
  if (score >= 60) return 'warning'
  return 'danger'
}
</script>

<style scoped>
.conversation-chat {
  display: grid;
  gap: 20px;
}

.turn-block {
  display: grid;
  gap: 12px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}

.turn-block:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.turn-index {
  color: var(--weak);
  font-size: 12px;
  letter-spacing: 0;
}

.message-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.assistant-row {
  justify-content: flex-start;
}

.user-row {
  justify-content: flex-end;
}

.message-stack {
  max-width: min(78%, 760px);
  display: grid;
  gap: 6px;
}

.message-name {
  color: var(--muted);
  font-size: 12px;
}

.user-name {
  text-align: right;
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  flex: 0 0 34px;
  font-weight: 800;
  font-size: 13px;
}

.avatar.model {
  color: #cbd5e1;
  background: #162033;
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.avatar.user {
  color: #06131a;
  background: linear-gradient(135deg, #2dd4bf, #38bdf8);
}

.bubble {
  border-radius: 14px;
  padding: 12px 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  box-shadow: 0 10px 24px rgba(2, 6, 23, 0.14);
}

.assistant-bubble {
  color: var(--body-text);
  background: rgba(22, 32, 51, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-top-left-radius: 6px;
}

.assistant-bubble.is-streaming::after {
  content: "";
  display: inline-block;
  width: 7px;
  height: 1em;
  margin-left: 4px;
  vertical-align: -2px;
  border-radius: 999px;
  background: var(--cyan-bright);
  animation: cursor-blink 0.9s steps(2, start) infinite;
}

.user-bubble {
  color: #eafcff;
  background: linear-gradient(135deg, rgba(14, 116, 144, 0.74), rgba(13, 148, 136, 0.68));
  border: 1px solid rgba(34, 211, 238, 0.22);
  border-top-right-radius: 6px;
}

.turn-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 2px;
}

.debug-collapse {
  margin-top: 2px;
}

.debug-note {
  margin: 0 0 8px;
  color: var(--muted);
  font-size: 12px;
}

.deduction-note {
  margin: 0;
  color: #f8d49a;
  font-size: 12px;
  line-height: 1.6;
}

.state-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.user-state-row {
  justify-content: flex-end;
}

.knowledge-row {
  display: grid;
  gap: 6px;
  margin-top: 2px;
  color: var(--muted);
  font-size: 12px;
}

.knowledge-row label {
  color: var(--muted);
}

.knowledge-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

:deep(.el-collapse) {
  border-color: rgba(148, 163, 184, 0.14);
}

:deep(.el-collapse-item__wrap),
:deep(.el-collapse-item__header) {
  color: var(--muted);
  background: rgba(15, 23, 42, 0.62);
  border-color: rgba(148, 163, 184, 0.14);
}

:deep(.el-collapse-item__content) {
  color: var(--body-text);
  background: rgba(15, 23, 42, 0.62);
}

@media (max-width: 720px) {
  .message-stack {
    max-width: 86%;
  }
}

@keyframes cursor-blink {
  0%,
  45% {
    opacity: 1;
  }
  46%,
  100% {
    opacity: 0;
  }
}
</style>
