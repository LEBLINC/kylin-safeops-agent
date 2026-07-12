/**
 * 安全策略与风险裁决类型
 *
 * 命名统一原则：
 * 1. 裁决只使用 allow / deny / confirm，不再使用 approval 表示“需确认”；
 * 2. 规则 ID 统一使用 rule_id，不再混用 id；
 * 3. 审批角色统一使用 approval_role，不再混用 approval_role；
 * 4. 工具名称统一使用 tool，不再混用 name / tool_name。
 */

/** 风险等级。R0 最低，R4 最高且一般禁止执行。 */
export type RiskLevel = 'R0' | 'R1' | 'R2' | 'R3' | 'R4'

/** 安全裁决结果。confirm 表示“需人工确认”。 */
export type PolicyDecision = 'allow' | 'deny' | 'confirm'

/** 系统角色。用于审批权限判断。 */
export type UserRole = 'viewer' | 'operator' | 'admin' | 'auditor'

/**
 * PolicyVerdict
 *
 * 一次工具计划的安全裁决结果。
 * 既可以表示整批最终裁决，也可以表示某个工具的逐工具裁决。
 */
export interface PolicyVerdict {
  /** 裁决动作：allow=允许，deny=拒绝，confirm=需确认。 */
  decision: PolicyDecision
  /** 整批或当前工具的最终风险等级。 */
  final_risk?: RiskLevel
  /** 命中的规则 ID 列表，例如 LOG001 / DBLOG001。 */
  matched_rules?: string[]
  /** 裁决原因。 */
  reason?: string
  /** 安全替代方案，例如“压缩轮转而不是直接删除”。 */
  safer_alternative?: string | null
  /** 是否需要人工确认。 */
  approval_required?: boolean
  /** 完成该确认所需的最低角色。 */
  approval_role?: UserRole | null
}

/** policy_verdict.data.per_tool[] 中的一项。 */
export interface PerToolVerdict {
  /** 工具名。 */
  tool: string
  /** 该工具自己的裁决结果。 */
  verdict: PolicyVerdict
}

/**
 * PolicyEvent
 *
 * 审计页或策略事件接口使用的策略事件记录。
 * 来源建议：GET /api/policy/events?trace_id=xxx。
 */
export interface PolicyEvent {
  event_id?: string
  trace_id: string
  /** 工具名，统一使用 tool。 */
  tool?: string
  final_risk?: RiskLevel
  decision: PolicyDecision
  /** 单条规则 ID，统一使用 rule_id。 */
  rule_id?: string
  /** 多条命中规则。 */
  matched_rules?: string[]
  reason: string
  safer_alternative?: string | null
  approval_required?: boolean
  approval_role?: UserRole | null
  created_at?: string
}

/**
 * PolicyRule
 *
 * 策略规则页展示的规则定义。
 * 来源建议：GET /api/policy/rules。
 */
export interface PolicyRule {
  /** 规则 ID，统一使用 rule_id（前端内部字段名；后端返回 id，API 层做映射）。 */
  rule_id: string
  /** 规则名称。 */
  name: string
  /** 规则详细描述（后端字段 description）。 */
  description?: string
  where?: string
  severity: string
  action: PolicyDecision
  reason?: string
  /** 审批所需最低角色。 */
  approval_role?: string | null
  safer_alternative?: string | null
}
