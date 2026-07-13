<script setup lang="ts">
/**
 * PageSection.vue
 *
 * 页面分区卡片组件，统一浅色卡片和 hover 动效。
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
        <h3 v-if="title || $slots.title"><slot name="title">{{ title }}</slot></h3>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
      <slot name="extra" />
    </header>
    <slot />
  </section>
</template>

<style scoped>
.page-section {
  padding: 18px;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 16px;
}
h3 {
  margin: 0;
  font-size: 16px;
  letter-spacing: -0.01em;
}
p {
  margin: 6px 0 0;
  color: var(--ks-text-muted);
  font-size: 13px;
  line-height: 1.5;
}
</style>
