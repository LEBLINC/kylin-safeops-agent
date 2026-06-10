<script setup lang="ts">
/**
 * MetricCard.vue
 *
 * 仪表盘指标卡组件。
 *
 * 使用位置：
 * - DashboardView.vue 顶部 CPU、内存、磁盘、工具调用、拦截次数等指标。
 *
 * 组件职责：
 * - 只负责卡片展示；
 * - 不请求接口；
 * - 不计算系统指标；
 * - 数据由 DashboardView.vue 从 /api/system/overview 或默认 Mock 中传入。
 */
defineProps<{
  /** 指标标题，例如“CPU 使用率”。 */
  title: string
  /** 指标值，例如 36%、128、5。 */
  value: string | number
  /** 指标说明，例如“实时采集”或“今日累计”。 */
  description?: string
  /** 指标状态，决定卡片光效颜色。 */
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
  padding: 18px;
  position: relative;
  overflow: hidden;
}
.metric::after {
  content: '';
  position: absolute;
  inset: auto -30px -40px auto;
  width: 120px;
  height: 120px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.16);
}
.metric.warning::after {
  background: rgba(245, 158, 11, 0.18);
}
.metric.danger::after {
  background: rgba(239, 68, 68, 0.18);
}
.metric-title {
  color: var(--ks-text-muted);
  font-size: 13px;
}
.metric-value {
  margin-top: 10px;
  font-size: 32px;
  font-weight: 800;
}
.metric-desc {
  margin-top: 8px;
  color: var(--ks-text-muted);
  font-size: 12px;
}
</style>
