export type ScenarioId = "A" | "B" | "C" | "D" | "E"
export type GateKey = "input" | "policy" | "confirm" | "result" | "audit"
export type GateStatus =
  | "protected" | "passed" | "waiting" | "approved"
  | "executed" | "recorded" | "skipped" | "not_reached" | "error"

export interface GateView { key: GateKey; name: string; status: GateStatus; label: string; detail: string }
export interface EvidenceItem { label: string; value: string; note?: string; tone?: "success" | "warning" | "danger" | "normal" }
export interface MetricItem { label: string; value: string; note: string }
export interface DemoResult {
  traceId: string
  outcome: "rejected" | "waiting" | "completed" | "failed"
  outcomeLabel: string
  decisionTitle: string
  decisionReason: string
  requestText: string
  actor: string
  action: string
  target: string
  gates: GateView[]
  metrics: MetricItem[]
  evidence: EvidenceItem[]
  events: Array<{ time: string; title: string; detail: string }>
  raw?: any
}
export interface Scenario {
  id: ScenarioId
  title: string
  technicalTitle: string
  risk: string
  summary: string
  focusGate: GateKey
  requestText: string
  action: string
  target: string
}
