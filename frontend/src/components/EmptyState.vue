<script setup lang="ts">
/**
 * EmptyState.vue
 *
 * 空状态组件。
 *
 * 使用位置：
 * - ChatView.vue 没有消息/工具结果/RCA 时；
 * - ApprovalView.vue 没有待审批时；
 * - AuditView.vue 没有审计记录时。
 *
 * 组件职责：
 * - 统一“暂无数据”的视觉样式；
 * - 避免页面因为数组为空而出现大面积空白。
 */
defineProps<{
  /** 空状态标题，例如“暂无审批”。 */
  title?: string
  /** 空状态说明，例如“等待后端推送或刷新页面后重试”。 */
  description?: string
}>()
</script>

<template>
  <div class="empty">
    <div class="icon">∅</div>
    <strong>{{ title || '暂无数据' }}</strong>
    <p>{{ description || '等待后端推送或刷新页面后重试' }}</p>
  </div>
</template>

<style scoped>
.empty {
  min-height: 180px;
  display: grid;
  place-items: center;
  text-align: center;
  color: var(--ks-text-muted);
}
.icon {
  width: 44px;
  height: 44px;
  border: 1px dashed var(--ks-border);
  border-radius: 999px;
  display: grid;
  place-items: center;
  font-size: 24px;
}
strong {
  color: var(--ks-text);
}
p {
  margin: 0;
}
</style>
