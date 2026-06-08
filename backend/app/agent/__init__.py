"""Agent 编排层（手册 §3.4）。

本轮仅状态机纯定义；orchestrator/planner/summarizer 后续增量补入。
"""

from backend.app.agent.orchestrator import Orchestrator, most_restrictive
from backend.app.agent.ports import AuditSink, EventSink, Executor, PolicyEngine
from backend.app.agent.state_machine import (
    INITIAL_STATE,
    TERMINAL_STATES,
    State,
    allowed_transitions,
    is_terminal,
    is_valid_transition,
)

__all__ = [
    # state machine
    "State",
    "INITIAL_STATE",
    "TERMINAL_STATES",
    "allowed_transitions",
    "is_terminal",
    "is_valid_transition",
    # ports
    "Executor",
    "AuditSink",
    "EventSink",
    "PolicyEngine",
    # orchestrator
    "Orchestrator",
    "most_restrictive",
]
