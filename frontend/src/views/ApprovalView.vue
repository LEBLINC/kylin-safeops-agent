<script setup lang="ts">
import { onMounted } from 'vue'
import ApprovalCard from '@/components/ApprovalCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import { useApprovalStore } from '@/stores/approval'

/**
 * ApprovalView.vue
 *
 * 风险审批页面。
 *
 * 页面作用：
 * - 给管理员集中处理待审批操作；
 * - 展示所有 pending 审批单；
 * - 支持通过/拒绝审批。
 *
 * 与 ChatView 内联审批的区别：
 * - ChatView：当前会话内即时审批，审批卡片显示在聊天区中间；
 * - ApprovalView：管理员集中审批所有待办，适合权限不足转交后的处理。
 *
 * 数据来源：
 * - useApprovalStore().pending；
 * - Store 内部调用 api/approval.ts 的 getPendingApprovals()。
 */
const approval = useApprovalStore()

/** 页面加载时拉取待审批列表。 */
onMounted(() => approval.load())

/**
 * 通过指定审批单。
 *
 * @param id 审批单 ID，即 ApprovalItem.approval_id。
 *
 * 调用链：
 * ApprovalCard emit approve
 *   → approveById(id)
 *   → approvalStore.approve(id)
 *   → POST /api/approvals/{id}/approve
 */
async function approveById(id?: string) {
  if (!id) return
  await approval.approve(id)
}

/**
 * 拒绝指定审批单。
 *
 * @param id 审批单 ID。
 *
 * 调用链：
 * ApprovalCard emit reject
 *   → rejectById(id)
 *   → approvalStore.reject(id)
 *   → POST /api/approvals/{id}/reject
 */
async function rejectById(id?: string) {
  if (!id) return
  await approval.reject(id)
}
</script>

<template>
  <div class="ks-page">
    <div class="approval-toolbar">
      <el-button type="primary" @click="approval.load()">刷新</el-button>
    </div>

    <div class="approval-grid" v-if="approval.pending.length">
      <ApprovalCard
        v-for="item in approval.pending"
        :key="item.approval_id"
        :item="item"
        @approve="approveById"
        @reject="rejectById"
      />
    </div>
    <EmptyState v-else title="暂无待审批操作" description="高危操作出现时会自动进入此列表" />
  </div>
</template>

<style scoped>
.approval-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 16px;
}
.approval-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
</style>
