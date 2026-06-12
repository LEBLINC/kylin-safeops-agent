# ruff: noqa: E501
"""RCA report and evidence data structures.
X maintains this package under mcp_servers/rca/.
No backend contract imports here; defines shapes consumed by RCA playbooks and the frontend RCA page.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# Four formal RCA scenarios + service_failure + one internal fallback.
RcaProblemType = Literal[
    "disk_full",
    "zombie_process",
    "io_high",
    "config_drift",
    "service_failure",
    "unknown",
]


class RcaEvidenceItem(TypedDict):
    """A single evidence item in evidence_chain.
    All tool outputs, log contents, and user descriptions are untrusted context.
    Each item carries is_untrusted for explicit UI annotation.
    """

    id: str
    source_tool: str
    title: str
    detail: str
    is_untrusted: bool


class RcaCandidate(TypedDict, total=False):
    """根因候选项。字段对齐前端 ``RcaCandidate``。

    Root cause candidate.
    """

    cause: str
    confidence: float
    evidence: list[str]
    evidence_refs: list[str]


class ApprovalRequiredAction(TypedDict):
    """需要审批才能执行的操作。适配前端 approval_required_actions 面板。

    An action that requires approval before execution.
    """

    action: str
    reason: str
    approval_role: str
    risk_level: str


class RcaEvidenceNode(TypedDict, total=False):
    """Evidence tree node for frontend EvidenceTree display."""

    id: str
    label: str
    value: str
    status: Literal["success", "warning", "danger", "info"]
    children: list[RcaEvidenceNode]


class RejectedDangerousAction(TypedDict, total=False):
    """被拒绝的危险动作。字段对齐前端定义。

    Rejected dangerous action.
    """

    action: str
    reason: str
    rule_id: str


class RcaReport(TypedDict, total=False):
    """RCA 最终报告（关键类型）。
    主链路 SSE：``rca -> {"report": RcaReport}``
    独立 RCA 页面：API 可补上 ``trace_id`` 后直接返回扁平 ``RcaResult``。

    RCA final report.
    """

    trace_id: str
    problem_type: RcaProblemType
    summary: str
    root_cause: str
    root_cause_candidates: list[RcaCandidate]
    confidence: float
    evidence_refs: list[str]
    evidence_chain: list[RcaEvidenceItem]
    recommendations: list[str]
    safe_actions: list[str]
    approval_required_actions: list[ApprovalRequiredAction]
    dangerous_actions_rejected: list[RejectedDangerousAction]
    risk_notes: list[str]
    recommended_next_steps: list[str]
    evidence_tree: list[RcaEvidenceNode]


_SUPPORTED_TYPES: set[str] = {
    "disk_full",
    "zombie_process",
    "io_high",
    "config_drift",
    "service_failure",
    "unknown",
}


def normalize_problem_type(problem_type: str | None) -> RcaProblemType | None:
    """Shared normalizer for playbooks and scenarios.
    Returns None for unrecognized types (caller treats as 'not specified').
    Returns 'unknown' only when explicitly passed 'unknown'.
    """
    if not problem_type:
        return None
    normalized = problem_type.strip().lower()
    alias: dict[str, str] = {
        "disk": "disk_full",
        "disk_usage": "disk_full",
        "disk_space": "disk_full",
        "zombie": "zombie_process",
        "process_zombie": "zombie_process",
        "io": "io_high",
        "iowait": "io_high",
        "config": "config_drift",
        "drift": "config_drift",
        "service": "service_failure",
        "service_failure": "service_failure",
    }
    normalized = alias.get(normalized, normalized)
    if normalized in _SUPPORTED_TYPES:
        return normalized  # type: ignore[return-value]
    return None


class RcaEvidenceStep(TypedDict, total=False):
    """A single evidence collection step.
    Describes what read-only tool L's API/orchestrator should call, without executing tools directly.
    Field 	ool follows project convention; do NOT use name/tool_name.
    """

    tool: str
    args: dict[str, Any]
    purpose: str
    evidence_key: str
    required: bool
    expected_signal: str


class RcaScenarioPlan(TypedDict):
    """一个 RCA 场景的完整采证模板。

    A complete evidence collection template for one RCA scenario.
    """

    problem_type: RcaProblemType
    title: str
    description: str
    trigger_keywords: list[str]
    evidence_steps: list[RcaEvidenceStep]
    report_focus: list[str]
    safety_notes: list[str]
