<template>
  <el-empty
    v-if="!turns.length"
    description="请在左侧选择任务和用例后开始评测"
  />
  <div v-else class="conversation-chat">
    <section v-for="item in turns" :key="item.key" class="turn-block">
      <div class="turn-index">第 {{ item.turnIndex }} 轮</div>

      <div class="message-row user-row">
        <div class="message-stack">
          <div class="message-name user-name">用户模拟器</div>
          <div class="bubble user-bubble">{{ item.userMessage || '暂无用户发言' }}</div>
        </div>
        <div class="avatar user">U</div>
      </div>

      <div class="message-row assistant-row">
        <div class="avatar model">M</div>
        <div class="message-stack">
          <div class="message-name">被测模型</div>
          <div class="bubble assistant-bubble">{{ item.assistantMessage || '暂无回复内容' }}</div>
          <div class="turn-meta">
            <el-tag type="info">响应 {{ item.latencyMs }} ms</el-tag>
            <el-tag :type="scoreType(item.score)">轮次得分 {{ item.score }}</el-tag>
            <el-tag
              v-for="rule in item.matchedRules"
              :key="`matched-${item.key}-${rule}`"
              type="success"
            >
              命中：{{ rule }}
            </el-tag>
            <el-tag
              v-for="rule in item.missedRules"
              :key="`missed-${item.key}-${rule}`"
              type="warning"
            >
              遗漏：{{ rule }}
            </el-tag>
            <el-tag
              v-for="rule in item.violatedRules"
              :key="`violated-${item.key}-${rule}`"
              type="danger"
            >
              违规：{{ rule }}
            </el-tag>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  messages: { type: Array, default: () => [] }
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

const turns = computed(() =>
  props.messages.map((item, index) => {
    const score = Number(item.rule_score ?? item.turn_score ?? item.score ?? 0)
    return {
      key: item.id || `${item.run_id || 'turn'}-${item.turn_index || index + 1}`,
      turnIndex: item.turn_index ?? item.turnIndex ?? index + 1,
      userMessage: pickMessage(item, 'user_message', 'user'),
      assistantMessage:
        pickMessage(item, 'assistant_message', 'assistant') ||
        pickMessage(item, 'model_message', 'model'),
      latencyMs: Number(item.latency_ms ?? item.latency ?? 0).toFixed(0),
      score: Number.isFinite(score) ? Number(score.toFixed(1)) : 0,
      matchedRules: toArray(item.matched_rules ?? item.matchedRules),
      missedRules: toArray(item.missed_rules ?? item.missedRules),
      violatedRules: toArray(item.violated_rules ?? item.violatedRules)
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

@media (max-width: 720px) {
  .message-stack {
    max-width: 86%;
  }
}
</style>
