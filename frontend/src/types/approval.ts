import type { RiskLevel, UserRole } from './policy'
import type { AwaitApprovalTool } from './chat'

/** 内联审批（对话流）状态。await_approval 事件 + 前端本地流转使用。 */
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'expired' | 'escalated'

/**
 * ApprovalItem
 *
 * 集中审批页 GET /api/approvals 的单条审批记录。
 * **严格对齐后端 schemas.py ApprovalItem**（仅 6 字段，不多不少）：
 * 后端主键是 trace_id（approve/reject 端点为 POST /{trace_id}/approve）。
 */
export interface ApprovalItem {
  /** 对应的 trace_id，也是 approve/reject 的主键。 */
  trace_id: string
  /** 用户原始意图（后端唯一的可读标题来源，无独立 title 字段）。 */
  user_intent: string
  /** 本批计划最高风险等级。 */
  risk_level: RiskLevel
  /** 完成该审批所需的角色；无则 null。 */
  approval_role: UserRole | null
  /** 状态机状态：WAIT_APPROVAL | FINISHED | REJECTED（后端原值，非 pending/approved）。 */
  state: string
  /** 创建时间。 */
  created_at: string
}

/**
 * InlineApproval
 *
 * 对话窗口中的内联审批卡片数据，来源 await_approval 事件。
 */
export interface InlineApproval {
  /** 当前等待审批的 trace_id。 */
  trace_id: string
  /** 审批原因。 */
  reason: string
  /** 本批需要确认的所有工具及角色要求。 */
  tools: AwaitApprovalTool[]
  /** 整批原子计划所需的最低角色。 */
  approval_role?: UserRole | null
  /** 当前内联审批状态。 */
  status: ApprovalStatus
}

/** GET /api/approvals 返回信封。后端返回 {items, total}，前端调用方需解包 .items。 */
export interface ApprovalListResponse {
  items: ApprovalItem[]
  total: number
}

/** POST /api/approvals/resume 请求体。后端 ResumeRequest 设置了 extra="forbid"，禁止多余字段。 */
export interface ResumeApprovalRequest {
  /** 要续跑或拒绝的 trace_id。 */
  trace_id: string
  /** true=批准整批执行；false=拒绝整批执行。 */
  approved: boolean
}

/** POST /api/approvals/resume 返回体。 */
export interface ResumeApprovalResponse {
  /** 对应 trace_id。 */
  trace_id: string
  /** 后端是否接受。 */
  accepted: boolean
}

/** POST /api/approvals/escalate 请求体。 */
export interface EscalateApprovalRequest {
  /** 需要转交审批的 trace_id。 */
  trace_id: string
  /** 转交审批备注。 */
  comment: string
  /** 需要管理员处理的工具列表。 */
  tools: AwaitApprovalTool[]
}

/** POST /api/approvals/escalate 返回体。 */
export interface EscalateApprovalResponse {
  trace_id: string
  status: 'submitted'
  message: string
}
