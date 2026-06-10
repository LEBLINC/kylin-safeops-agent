<script setup lang="ts">
/**
 * PageHeader.vue
 *
 * 页面标题组件。
 *
 * 使用位置：
 * - 所有 views 页面顶部。
 *
 * 组件职责：
 * - 统一页面标题和副标题样式；
 * - 通过默认插槽支持右侧按钮，例如刷新、导出、创建会话等。
 */
defineProps<{
  /** 页面主标题，例如“智能对话”。 */
  title: string
  /** 页面副标题，用于解释页面用途。 */
  subtitle?: string
}>()
</script>

<template>
  <div class="page-header">
    <div>
      <h1>{{ title }}</h1>
      <p v-if="subtitle">{{ subtitle }}</p>
    </div>
    <!-- 默认插槽：页面右侧操作按钮区域。 -->
    <slot />
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
h1 {
  margin: 0;
  font-size: 24px;
  letter-spacing: 0.2px;
}
p {
  margin: 8px 0 0;
  color: var(--ks-text-muted);
}
</style>
