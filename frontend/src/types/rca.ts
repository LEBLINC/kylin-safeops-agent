/**
 * RCA supported problem types.
 * Five formal scenarios + unknown fallback.
 * Aliases service_abnormal / service_failed map to service_failure in Python backend.
 */
export type RcaProblemType =
  | 'disk_full'
  | 'zombie_process'
  | 'io_high'
  | 'config_drift'
  | 'service_failure'
  | 'unknown'

/** Root cause candidate. */
export interface RcaCandidate {
  cause: string
  confidence: number
  evidence: string[]
  evidence_refs?: string[]
}

/** An action that requires approval before execution. */
export interface ApprovalRequiredAction {
  action: string
  reason: string
  approval_role: string
  risk_level: string
}

/** EvidenceTree component tree node. */
export interface RcaEvidenceNode {
  id: string
  label: string
  value?: string
  status?: 'success' | 'warning' | 'danger' | 'info'
  children?: RcaEvidenceNode[]
}

/** A single evidence item in evidence_chain. */
export interface RcaEvidenceItem {
  id: string
  source_tool: string
  title: string
  detail: string
  is_untrusted: boolean
}

/** Rejected dangerous action. */
export interface RejectedDangerousAction {
  action: string
  reason: string
  rule_id?: string
}

/**
 * RcaReport
 *
 * rca event data.report structure.
 * stream.py specifies report is a dict; this is the recommended alignment
 * between frontend and mcp_servers/rca/.
 */
export interface RcaReport {
  /** Problem type. */
  problem_type: RcaProblemType
  /** Analysis summary. */
  summary: string
  /** Primary root cause (derived from top candidate). */
  root_cause: string
  /** Root cause candidates. */
  root_cause_candidates: RcaCandidate[]
  /** Confidence of the primary root cause (0-1). */
  confidence: number
  /** All evidence references from candidates. */
  evidence_refs: string[]
  /** Evidence chain (untrusted). */
  evidence_chain: RcaEvidenceItem[]
  /** Human-readable recommendations. */
  recommendations: string[]
  /** Safe read-only or low-risk actions. */
  safe_actions: string[]
  /** Actions requiring approval before execution. */
  approval_required_actions: ApprovalRequiredAction[]
  /** Dangerous actions rejected by safety policy. */
  dangerous_actions_rejected: RejectedDangerousAction[]
  /** Risk notes and caveats. */
  risk_notes: string[]
  /** Recommended next steps (legacy compat). */
  recommended_next_steps: string[]
  /** Evidence tree for UI display. */
  evidence_tree: RcaEvidenceNode[]
}

/**
 * RcaResult
 *
 * Standalone RCA page interface return structure.
 */
/** GET /api/rca/{trace_id} backend response wrapper. */
export interface RcaApiResponse {
  trace_id: string
  report: RcaReport
}

export interface RcaResult {
  trace_id: string
  problem_type: RcaProblemType
  root_cause?: string
  summary?: string
  root_cause_candidates: RcaCandidate[]
  confidence?: number
  evidence_refs?: string[]
  recommendations?: string[]
  safe_actions: string[]
  approval_required_actions?: ApprovalRequiredAction[]
  dangerous_actions_rejected: RejectedDangerousAction[]
  risk_notes?: string[]
  evidence_tree?: RcaEvidenceNode[]
  evidence_chain?: RcaEvidenceItem[]
  recommended_next_steps?: string[]
}
