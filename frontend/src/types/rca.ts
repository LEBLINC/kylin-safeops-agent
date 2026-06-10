/**
 * RCA 支持的问题类型。
 * 该类型不在 stream.py 中强约束；stream.py 只规定 rca -> { report: dict }。
 */
export type RcaProblemType =
  | 'disk_full'
  | 'zombie_process'
  | 'io_high'
  | 'config_drift'
  | 'service_abnormal'
  | 'service_failed'
  | 'unknown'

/** 根因候选项。 */
export interface RcaCandidate {
  /** 根因描述。 */
  cause: string
  /** 置信度，0~1。 */
  confidence: number
  /** 直接证据文本。 */
  evidence: string[]
  /** 对 evidence_chain 中证据节点的引用 ID。 */
  evidence_refs?: string[]
}

/** EvidenceTree 组件使用的树形节点。 */
export interface RcaEvidenceNode {
  id: string
  label: string
  value?: string
  status?: 'success' | 'warning' | 'danger' | 'info'
  children?: RcaEvidenceNode[]
}

/** RCA 证据链中的一条证据。 */
export interface RcaEvidenceItem {
  /** 证据 ID。 */
  id: string
  /** 证据来自哪个工具，例如 disk.usage / process.zombie_check。 */
  source_tool: string
  /** 证据标题。 */
  title: string
  /** 证据详情。 */
  detail: string
  /** 是否不可信。来自工具输出/日志的证据必须标记为 true。 */
  is_untrusted: boolean
}

/** 被拒绝的危险操作。 */
export interface RejectedDangerousAction {
  action: string
  reason: string
  rule_id?: string
}

/**
 * RcaReport
 *
 * rca 事件 data.report 的建议结构。
 * 说明：stream.py 目前只规定 report 是 dict，没有展开字段；
 * 这里是前端与 mcp_servers/rca/ 建议对齐的结构。
 */
export interface RcaReport {
  problem_type: RcaProblemType
  summary: string
  root_cause_candidates: RcaCandidate[]
  evidence_chain: RcaEvidenceItem[]
  safe_actions: string[]
  dangerous_actions_rejected: RejectedDangerousAction[]
  recommended_next_steps: string[]
}

/**
 * RcaResult
 *
 * 独立 RCA 页面接口返回结构。
 * 这里兼容旧 EvidenceTree 的 evidence_tree，同时也兼容新的 RcaReport 字段。
 */
export interface RcaResult {
  /** RCA 任务 ID。 */
  trace_id: string
  /** 问题类型。 */
  problem_type: RcaProblemType
  /** 分析摘要。 */
  summary?: string
  /** 根因候选。 */
  root_cause_candidates: RcaCandidate[]
  /** 安全建议。 */
  safe_actions: string[]
  /** 被拒绝的危险操作，兼容旧 string[] 与新版对象数组。 */
  dangerous_actions_rejected: string[] | RejectedDangerousAction[]
  /** 旧版树形证据结构。 */
  evidence_tree?: RcaEvidenceNode[]
  /** 新版证据链结构。 */
  evidence_chain?: RcaEvidenceItem[]
  /** 推荐下一步操作。 */
  recommended_next_steps?: string[]
}
