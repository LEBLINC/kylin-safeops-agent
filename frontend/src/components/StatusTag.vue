<script setup lang="ts">
/**
 * StatusTag.vue
 *
 * 通用状态标签组件。
 *
 * 使用位置：
 * - ApprovalCard.vue 展示 pending/approved/rejected；
 * - AuditView.vue 展示审计状态；
 * - DashboardView.vue 展示服务状态；
 * - ToolCallCard.vue 展示工具执行状态。
 *
 * 设计说明：
 * - 后端不同接口可能返回 success、failed、allow、confirm 等不同状态值；
 * - 本组件统一把这些英文值转换成中文标签。
 */
const props = defineProps<{
  /** 状态值，例如 success、failed、running、pending、allow、deny、confirm。 */
  status?: string
}>()

/**
 * 将状态值映射为中文文案和 Element Plus 标签类型。
 *
 * 如果状态值未出现在 map 中，则原样显示，避免后端新增状态时页面空白。
 */
function tag() {
  const map: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
    success: { label: '成功', type: 'success' },
    failed: { label: '失败', type: 'danger' },
    error: { label: '错误', type: 'danger' },
    running: { label: '执行中', type: 'primary' },
    pending: { label: '待处理', type: 'warning' },
    approved: { label: '已通过', type: 'success' },
    rejected: { label: '已拒绝', type: 'danger' },
    escalated: { label: '已转审批', type: 'warning' },
    allow: { label: '允许', type: 'success' },
    deny: { label: '拒绝', type: 'danger' },
    confirm: { label: '需确认', type: 'warning' }
  }
  return map[props.status || ''] || { label: props.status || '未知', type: 'info' as const }
}
</script>

<template>
  <el-tag :type="tag().type" effect="dark">{{ tag().label }}</el-tag>
</template>
