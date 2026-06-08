"""Kylin SafeOps Agent 契约层（冻结物，手册 §1.3）。

6 份契约 = 全队唯一事实来源。D / X 拿桩并行开发。
冻结纪律：任何改动须 L 本人 review + 通知 D、X，且单独成 commit（前缀 contract:）。
"""

from backend.app.contracts.audit import (
    GENESIS_HASH,
    AuditRecord,
    canonical_json,
    compute_curr_hash,
)
from backend.app.contracts.intent import CandidateTool, Intent, RiskHint
from backend.app.contracts.policy import Decision, PolicyEngine, PolicyVerdict
from backend.app.contracts.stream import EventType, StreamEvent
from backend.app.contracts.tool import RiskLevel, ToolSpec
from backend.app.contracts.untrusted import UNTRUSTED_WRAP_TOKEN, ToolResult

__all__ = [
    # tool
    "RiskLevel",
    "ToolSpec",
    # intent
    "RiskHint",
    "CandidateTool",
    "Intent",
    # policy
    "Decision",
    "PolicyVerdict",
    "PolicyEngine",
    # untrusted
    "UNTRUSTED_WRAP_TOKEN",
    "ToolResult",
    # audit
    "GENESIS_HASH",
    "AuditRecord",
    "canonical_json",
    "compute_curr_hash",
    # stream
    "EventType",
    "StreamEvent",
]
