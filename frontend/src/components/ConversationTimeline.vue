<template>
  <el-timeline class="conversation">
    <el-timeline-item
      v-for="item in messages"
      :key="item.id || item.turn_index"
      :timestamp="`第 ${item.turn_index} 轮 · ${item.latency_ms || 0} ms`"
      placement="top"
    >
      <div class="turn">
        <div class="bubble user">
          <label>用户</label>
          <p>{{ item.user_message }}</p>
        </div>
        <div class="bubble assistant">
          <label>被测模型</label>
          <p>{{ item.assistant_message }}</p>
        </div>
        <div class="turn-meta">
          <el-tag type="success">轮次得分 {{ item.rule_score || 0 }}</el-tag>
          <el-tag v-for="rule in item.matched_rules || []" :key="rule" type="info">{{ rule }}</el-tag>
          <el-tag v-for="rule in item.violated_rules || []" :key="rule" type="danger">{{ rule }}</el-tag>
        </div>
      </div>
    </el-timeline-item>
  </el-timeline>
</template>

<script setup>
defineProps({
  messages: { type: Array, default: () => [] }
})
</script>

<style scoped>
.conversation {
  padding-left: 4px;
}

.turn {
  display: grid;
  gap: 10px;
}

.bubble {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  background: #0d141c;
}

.bubble.user {
  border-color: rgba(88, 166, 255, 0.28);
}

.bubble.assistant {
  border-color: rgba(53, 211, 199, 0.28);
}

label {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 6px;
}

p {
  margin: 0;
  line-height: 1.7;
}

.turn-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
