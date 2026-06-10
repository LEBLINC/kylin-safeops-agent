<script setup lang="ts">
/**
 * PageSection.vue
 *
 * 页面分区卡片组件。
 *
 * 使用位置：
 * - DashboardView.vue、AuditView.vue、PolicyView.vue、RcaView.vue 等页面。
 *
 * 组件职责：
 * - 统一“卡片 + 标题 + 副标题 + 右上角扩展区域”的布局；
 * - 减少每个页面重复写 ks-card、header 样式。
 */
defineProps<{
  /** 分区标题，例如“最近安全裁决”。 */
  title?: string
  /** 分区副标题，用于解释该区域数据来源或用途。 */
  subtitle?: string
}>()
</script>

<template>
  <section class="page-section ks-card">
    <header v-if="title || subtitle" class="section-header">
      <div>
        <h3 v-if="title">{{ title }}</h3>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
      <!-- extra 插槽：给页面放按钮、筛选器、刷新操作等。 -->
      <slot name="extra" />
    </header>
    <!-- 默认插槽：分区主体内容。 -->
    <slot />
  </section>
</template>

<style scoped>
.page-section {
  padding: 16px;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
h3 {
  margin: 0;
  font-size: 16px;
}
p {
  margin: 6px 0 0;
  color: var(--ks-text-muted);
  font-size: 13px;
}
</style>
