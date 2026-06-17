<script setup lang="ts">
/**
 * MetricCard.vue
 *
 * 通用指标卡组件。
 * 当前保留兼容 Dashboard 之外的使用场景，并统一为浅色 hover 卡片风格。
 */
defineProps<{
  /** 指标标题，例如“CPU 使用率”。 */
  title: string
  /** 指标值，例如 36%、128、5。 */
  value: string | number
  /** 指标说明，例如“实时采集”或“今日累计”。 */
  description?: string
  /** 指标状态，决定卡片强调色。 */
  status?: 'normal' | 'warning' | 'danger'
}>()
</script>

<template>
  <div class="metric ks-card" :class="status">
    <div class="metric-title">{{ title }}</div>
    <div class="metric-value">{{ value }}</div>
    <div class="metric-desc">{{ description || '实时采集' }}</div>
  </div>
</template>

<style scoped>
.metric {
  --ks-card-gradient: var(--ks-gradient-blue);
  --ks-card-hover-gradient: var(--ks-gradient-blue-hover);
  --ks-accent: var(--ks-primary);
  --ks-accent-rgb: 37, 99, 235;
  padding: 18px;
  position: relative;
  overflow: hidden;
}
.metric.warning {
  --ks-card-gradient: var(--ks-gradient-amber);
  --ks-card-hover-gradient: var(--ks-gradient-amber-hover);
  --ks-accent: var(--ks-warning);
  --ks-accent-rgb: 245, 158, 11;
}
.metric.danger {
  --ks-card-gradient: var(--ks-gradient-rose);
  --ks-card-hover-gradient: var(--ks-gradient-rose-hover);
  --ks-accent: var(--ks-danger);
  --ks-accent-rgb: 239, 68, 68;
}
.metric::after {
  content: '';
  position: absolute;
  inset: auto -30px -40px auto;
  width: 120px;
  height: 120px;
  border-radius: 999px;
  background: rgba(var(--ks-accent-rgb), 0.12);
  transition: transform 180ms ease, opacity 180ms ease;
}
.metric:hover::after {
  transform: scale(1.12);
  opacity: 0.9;
}
.metric.warning::after {
  background: rgba(245, 158, 11, 0.14);
}
.metric.danger::after {
  background: rgba(239, 68, 68, 0.12);
}
.metric-title {
  color: var(--ks-text-muted);
  font-size: 13px;
  font-weight: 700;
}
.metric-value {
  margin-top: 10px;
  font-size: 32px;
  font-weight: 800;
  color: var(--ks-text);
}
.metric-desc {
  margin-top: 8px;
  color: var(--ks-text-muted);
  font-size: 12px;
}
</style>
