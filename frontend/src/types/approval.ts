import type { RiskLevel, UserRole } from './policy'
import type { AwaitApprovalTool } from './chat'

/** 审批单状态。 */
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'expired' | 'escalated'

/**
 * ApprovalItem
 *
 * 风险审批页中的审批单。
 * 命名统一原则：
 * - 工具名称使用 tool；
 * - 所需审批角色使用 approval_role；
 * - 用户审批/拒绝/转交时填写的备注统一使用 comment。
 */
export interface ApprovalItem {
  /** 审批单 ID，审批页列表/详情使用。 */
  approval_id: string
  /** 对应的 trace_id，用于回到审计链路或续跑原子计划。 */
  trace_id: string
  /** 审批单标题。 */
  title: string
  /** 单工具展示时使用；多工具审批时以 tools 列表为主。 */
  tool?: string
  /** 多工具审批列表。 */
  tools?: AwaitApprovalTool[]
  /** 本批计划最高风险等级。 */
  risk_level: RiskLevel
  /** 当前审批状态。 */
  status: ApprovalStatus
  /** 为什么需要审批，这是系统给出的审批原因，不是用户备注。 */
  reason: string
  /** 完成该审批所需的最低角色。 */
  approval_role?: UserRole | null
  /** 工具参数。 */
  args?: Record<string, unknown>
  /** dry-run 结果，展示影响范围。 */
  dry_run?: {
    passed: boolean
    impact?: string
    output?: unknown
  }
  /** 创建时间。 */
  created_at?: string
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
