"""D15 RCA 接入点测试：默认 NullRCA 不 emit；注入 RCA 拿到证据并 emit "rca" 事件。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.rca import NullRCA, RCAEngine
from backend.app.agent.state_machine import State
from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.stream import StreamEvent
from backend.app.contracts.tool import ToolSpec
from backend.app.contracts.untrusted import ToolResult
from backend.app.llm.adapter import LLMAdapter
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry

_SPEC = ToolSpec(
    name="disk.usage",
    description="d",
    risk="R0",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    requires_roles=["operator"],
    reversible=True,
)


class _Policy:
    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return PolicyVerdict(
            decision="allow",
            final_risk="R0",
            matched_rules=[],
            reason="ok",
            approval_required=False,
        )


class _Executor:
    async def execute(self, tool: CandidateTool) -> ToolResult:
        return ToolResult(tool=tool.name, args=tool.args, exit_code=0, stdout_truncated="ok")


class _Audit:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


class _Events:
    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    def emit(self, event: StreamEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type for e in self.events]


def _llm_returning(output: str) -> LLMAdapter:
    async def fn(messages):  # noqa: ANN001
        return output

    return LLMAdapter(completion_fn=fn)


_INTENT = json.dumps(
    {
        "intent": "x",
        "confidence": 0.9,
        "need_observation": False,
        "candidate_tools": [{"name": "disk.usage", "args": {}}],
        "risk_hint": "low",
        "justification": "j",
    }
)


def _build(rca: RCAEngine | None):  # noqa: ANN201
    audit, events = _Audit(), _Events()
    gateway = MCPGateway(ToolRegistry([_SPEC]), _Policy(), _Executor())
    orch = Orchestrator(
        llm=_llm_returning(_INTENT), gateway=gateway, audit=audit, events=events, rca=rca
    )
    return orch, events


def test_default_null_rca_emits_no_rca_event() -> None:
    orch, events = _build(rca=None)
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.FINISHED
    assert "rca" not in events.types()  # NullRCA 返回 {} → 不 emit


def test_explicit_null_rca_same_as_default() -> None:
    orch, events = _build(rca=NullRCA())
    asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert "rca" not in events.types()


def test_injected_rca_receives_evidence_and_emits() -> None:
    captured: list[Sequence[ToolResult]] = []

    class CapturingRCA:
        def analyze(self, evidence: Sequence[ToolResult]) -> dict:
            captured.append(list(evidence))
            return {"root_cause": "disk full", "confidence": 0.7, "evidence_count": len(evidence)}

    orch, events = _build(rca=CapturingRCA())
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.FINISHED

    # RCA 收到了执行结果作为证据（本例 1 个工具）
    assert len(captured) == 1
    assert len(captured[0]) == 1
    assert captured[0][0].tool == "disk.usage"
    assert captured[0][0].is_untrusted is True  # 证据均已密封

    # rca 事件被 emit，data.report 是字典
    rca_events = [e for e in events.events if e.type == "rca"]
    assert len(rca_events) == 1
    assert rca_events[0].data["report"]["root_cause"] == "disk full"

    # rca 在 verified 之后、finished 之前 emit（编排顺序正确）
    type_seq = events.types()
    assert type_seq.index("verified") < type_seq.index("rca")


def test_rca_runs_after_observation_and_execution_evidence_combined() -> None:
    """observe→re-plan 两阶段下，RCA 拿到的证据 = 观测结果 + 执行结果。"""
    first = json.dumps(
        {
            "intent": "obs",
            "confidence": 0.9,
            "need_observation": True,
            "candidate_tools": [{"name": "disk.usage", "args": {}}],
            "risk_hint": "low",
            "justification": "obs",
        }
    )
    second = json.dumps(
        {
            "intent": "act",
            "confidence": 0.9,
            "need_observation": False,
            "candidate_tools": [{"name": "disk.usage", "args": {}}],
            "risk_hint": "low",
            "justification": "act",
        }
    )

    seq = [first, second]
    calls = {"n": 0}

    async def fn(messages):  # noqa: ANN001
        out = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return out

    captured: list[int] = []

    class CountingRCA:
        def analyze(self, evidence: Sequence[ToolResult]) -> dict:
            captured.append(len(evidence))
            return {"n": len(evidence)}

    audit, events = _Audit(), _Events()
    gateway = MCPGateway(ToolRegistry([_SPEC]), _Policy(), _Executor())
    orch = Orchestrator(
        llm=LLMAdapter(completion_fn=fn),
        gateway=gateway,
        audit=audit,
        events=events,
        rca=CountingRCA(),
    )
    asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    # 观测 1 个 + 执行 1 个 = 2
    assert captured == [2]
