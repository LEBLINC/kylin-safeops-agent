import { defineStore } from 'pinia'
import { approveAction, getPendingApprovals, rejectAction } from '@/api/approval'
import { isMockEnabled } from '@/api/mock'
import type { ApprovalItem } from '@/types/approval'

/**
 * approval.ts Store
 *
 * 风险审批页的全局状态管理。
 *
 * 使用位置：
 * - ApprovalView.vue 管理员集中审批页面。
 *
 * 和 ChatView 内联审批的区别：
 * - ChatView 中的审批是“当前对话里的即时审批”，数据来自 await_approval 事件；
 * - ApprovalView 中的审批是“管理员集中审批待办”，数据来自 /api/approvals REST 接口。
 *
 * Mock 说明：
 * - 如果后端审批列表接口不可用，本 Store 会生成一条 mock 审批单，保证页面可演示。
 */
export const useApprovalStore = defineStore('approval', {
  /**
   * state
   *
   * @field pending 当前审批页展示的审批单列表。
   * @field loading 审批列表是否正在加载，用于页面 loading/禁用状态。
   */
  state: () => ({
    pending: [] as ApprovalItem[],
    loading: false
  }),

  actions: {
    /**
     * 加载待审批列表。
     *
     * 数据流：
     * ApprovalView.vue onMounted()
     *   → approvalStore.load()
     *   → api/approval.ts getPendingApprovals()
     *   → GET /api/approvals?status=pending
     *
     * 失败兜底：
     * - 如果后端未启动或接口未实现，catch 中放入 mock_ap_001，方便页面演示。
     */
    async load() {
      this.loading = true
      try {
        this.pending = await getPendingApprovals()
      } catch {
        if (!isMockEnabled()) return
        this.pending = [
          {
            approval_id: 'mock_ap_001',
            trace_id: 'mock_trace',
            title: '压缩并轮转 /var/log/app.log',
            tool: 'log.compress_rotate',
            risk_level: 'R2',
            status: 'pending',
            reason: '涉及日志文件变更，需要管理员确认',
            approval_role: 'admin',
            args: { path: '/var/log/app.log' },
            dry_run: { passed: true, impact: '会生成 .gz 归档文件，不直接删除原始日志' }
          }
        ]
      } finally {
        this.loading = false
      }
    },

    /**
     * 通过某条审批单。
     *
     * 使用位置：
     * - ApprovalView.vue 中 ApprovalCard emit approve 后调用。
     *
     * 入参：
     * @param id approval_id 审批单 ID。
     *
     * 后端接口：
     * - POST /api/approvals/{approval_id}/approve
     *
     * 前端行为：
     * - 接口成功后把本地 pending 中对应项改为 approved；
     * - 接口失败时仍本地改状态，保证演示不中断。
     */
    async approve(id: string) {
      try {
        await approveAction(id)
      } catch {
        // Mock/演示兜底：后端不可用时仍让页面状态更新。
      }
      this.pending = this.pending.map(item => item.approval_id === id ? { ...item, status: 'approved' } : item)
    },

    /**
     * 拒绝某条审批单。
     *
     * 使用位置：
     * - ApprovalView.vue 中 ApprovalCard emit reject 后调用。
     *
     * 入参：
     * @param id approval_id 审批单 ID。
     *
     * 后端接口：
     * - POST /api/approvals/{approval_id}/reject
     *
     * 前端行为：
     * - 接口成功后把本地 pending 中对应项改为 rejected；
     * - 接口失败时仍本地改状态，保证演示不中断。
     */
    async reject(id: string) {
      try {
        await rejectAction(id)
      } catch {
        // Mock/演示兜底：后端不可用时仍让页面状态更新。
      }
      this.pending = this.pending.map(item => item.approval_id === id ? { ...item, status: 'rejected' } : item)
    }
  }
})
