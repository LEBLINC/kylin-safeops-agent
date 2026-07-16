import { request } from './request'
import { isMockEnabled } from '@/api/mock-flag'
import type {
  ApprovalItem,
  ApprovalListResponse,
  EscalateApprovalRequest,
  EscalateApprovalResponse,
  ResumeApprovalRequest,
  ResumeApprovalResponse
} from '@/types/approval'

/**
 * approval.ts
 *
 * 审批相关接口封装模块。
 *
 * 使用位置：
 * - ApprovalView.vue：管理员集中查看、批准、拒绝审批单；
 * - ChatView.vue：对话中出现 await_approval 事件时，用户直接在聊天窗口里处理；
 * - stores/chat.ts：approveInlinePlan / rejectInlinePlan / escalateInlineApproval 会调用这里。
 *
 * 接口语义：
 * - /api/approvals/resume：批准或拒绝当前 trace 的整批原子计划；
 * - /api/approvals/escalate：当前用户权限不足时，把审批申请提交给管理员队列。
 *
 * Mock 行为：
 * - VITE_MOCK_ENABLED=true 时，所有接口转到 src/api/mock.ts；
 * - resumeApproval 在 Mock 中会继续推动同一个 mock StreamEvent 流，模拟后端续跑；
 * - escalateApproval 在 Mock 中只返回“已提交管理员审批”，不会执行工具。
 */

/**
 * 获取待审批列表。
 *
 * 请求方式：GET /api/approvals?status=pending
 *
 * 使用位置：ApprovalView.vue
 *
 * 返回字段：
 * - approval_id：审批单 ID；
 * - trace_id：对应的执行链路；
 * - title/reason：审批说明；
 * - risk_level/status/required_role：风险、状态、审批角色；
 * - dry_run：执行前影响范围。
 */
export async function getPendingApprovals() {
  if (isMockEnabled()) { const { mockGetPendingApprovals } = await import("./mock"); return mockGetPendingApprovals() }
  // 后端返回信封 {items, total}，解包 items 给 store（store 期望裸数组）
  const res = await request.get<ApprovalListResponse, ApprovalListResponse>('/api/approvals', {
    params: { status: 'pending' }
  })
  return (res as unknown as ApprovalListResponse).items
}

/**
 * 获取单个审批单详情。
 *
 * 请求方式：GET /api/approvals/{approval_id}
 *
 * 使用位置：ApprovalView.vue 点击某条审批单查看详情。
 */
export async function getApprovalDetail(approvalId: string) {
  if (isMockEnabled()) { const { mockGetApprovalDetail } = await import("./mock"); return mockGetApprovalDetail(approvalId) }
  return request.get<ApprovalItem, ApprovalItem>(`/api/approvals/${approvalId}`)
}

/**
 * 集中审批页批准审批单。
 *
 * 请求方式：POST /api/approvals/{approval_id}/approve
 *
 * 注意：这是 ApprovalView 的旧式审批单接口；ChatView 对话内审批统一使用 resumeApproval()。
 */
export async function approveAction(approvalId: string) {
  if (isMockEnabled()) { const { mockApproveAction } = await import("./mock"); return mockApproveAction(approvalId) }
  return request.post(`/api/approvals/${approvalId}/approve`)
}

/**
 * 集中审批页拒绝审批单。
 *
 * 请求方式：POST /api/approvals/{approval_id}/reject
 * 请求体：{ comment?: string }
 */
export async function rejectAction(approvalId: string, comment?: string) {
  if (isMockEnabled()) { const { mockRejectAction } = await import("./mock"); return mockRejectAction(approvalId, comment) }
  return request.post(`/api/approvals/${approvalId}/reject`, { comment })
}

/**
 * 对话内审批续跑接口。
 *
 * 请求方式：POST /api/approvals/resume
 * 使用位置：stores/chat.ts 的 approveInlinePlan / rejectInlinePlan
 *
 * 请求参数（禁止多加字段，后端 extra="forbid"）：
 * @param data.trace_id 当前等待审批的 trace_id。
 * @param data.approved true 表示批准整批原子计划；false 表示拒绝整批原子计划。
 *
 * 返回数据：
 * @returns trace_id 对应 trace。
 * @returns accepted 后端是否接受。
 *
 * 原子语义：
 * 这个接口不是逐工具审批，而是对 await_approval.data.tools 中的整批工具统一批准或拒绝。
 */
export async function resumeApproval(data: ResumeApprovalRequest) {
  if (isMockEnabled()) { const { mockResumeApproval } = await import("./mock"); return mockResumeApproval(data) }
  return request.post<ResumeApprovalResponse, ResumeApprovalResponse>('/api/approvals/resume', data)
}

/**
 * 权限不足时提交管理员审批申请。
 *
 * 请求方式：POST /api/approvals/escalate
 * 使用位置：ChatView.vue 中间聊天区的“申请转管理员审批”按钮。
 *
 * 请求参数：
 * @param data.trace_id 当前等待审批的 trace_id。
 * @param data.comment 转交审批备注，例如“当前用户权限不足”。
 * @param data.tools 本批待审批工具列表，来自 await_approval.data.tools。
 *
 * 返回数据：
 * @returns trace_id 对应 trace。
 * @returns status 固定为 submitted。
 * @returns message 展示给用户的提示语。
 *
 * 注意：
 * 该接口不会续跑工具，也不会触发 executing/tool_result；它只是把审批单提交给管理员待办。
 */
export async function escalateApproval(data: EscalateApprovalRequest) {
  if (isMockEnabled()) { const { mockEscalateApproval } = await import("./mock"); return mockEscalateApproval(data) }
  return request.post<EscalateApprovalResponse, EscalateApprovalResponse>('/api/approvals/escalate', data)
}
