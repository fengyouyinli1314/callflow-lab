<template>
  <div class="metric-card panel">
    <div class="metric-icon" :style="{ color }">
      <component :is="icon" />
    </div>
    <div>
      <span>{{ label }}</span>
      <strong>{{ value }}</strong>
      <small v-if="suffix">{{ suffix }}</small>
    </div>
  </div>
</template>

<script setup>
defineProps({
  label: String,
  value: [String, Number],
  suffix: String,
  icon: { type: String, default: 'DataLine' },
  color: { type: String, default: '#35d3c7' }
})
</script>

<style scoped>
.metric-card {
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 104px;
}

.metric-icon {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.06);
}

.metric-icon :deep(svg) {
  width: 22px;
  height: 22px;
}

span {
  color: var(--muted);
  display: block;
  font-size: 13px;
}

strong {
  display: inline-block;
  font-size: 28px;
  margin-top: 4px;
}

small {
  margin-left: 6px;
  color: var(--muted);
}
</style>
