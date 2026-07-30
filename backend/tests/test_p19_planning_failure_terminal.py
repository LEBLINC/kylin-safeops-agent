"""P1-9: LLM 规划失败后 trace 卡在非终态，永不闭合。

RECEIVED 期 self._llm.plan() 抛异常时，orchestrator 审计 + emit error 之后
直接 `return self.state`——状态仍是 RECEIVED，一个非终态。CONTEXT_COLLECTED
期的 re-plan 失败是同一形状。

后果是双重的，且都不会报错，只会慢慢烂：
  ① audit_logger 的 retention 终态闸按 phase IN (FINISHED/REJECTED/FAILED)
     判定，这类 trace 永远算 in-flight → 永不清理，审计库无界增长；
  ② SessionRegistry.is_finished 取 is_terminal(orchestrator.state)，
     恒 False → 会话永不释放。

R-2 已为 EXECUTING 期系统故障建了 FAILED 终态并写明了这三个洞，
但只覆盖了执行期；规划期的两处同病漏修。本用例钉住两处都收敛到 FAILED。

  F-1 RECEIVED 期 plan 失败 → 终态 FAILED（非 RECEIVED）
  F-2 CONTEXT_COLLECTED 期 re-plan 失败 → 终态 FAILED
  F-3 失败留下 FAILED phase 的审计记录（retention 终态闸据此才认得它）
  F-4 FAILED 与 REJECTED 语义不混用——规划失败不得记成安全拒绝
"""

from __future__ import annotations

import asyncio

import httpx

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.state_machine import State, is_terminal
from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import Intent
from backend.app.contracts.stream import StreamEvent


class _Audit:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)

    def phases(self) -> list[str]:
        return [r.phase for r in self.records]


class _Events:
    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    def emit(self, event: StreamEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type for e in self.events]


class _FailingPlanLLM:
    """首次 plan 即抛——复现 RECEIVED 期规划失败。"""

    async def plan(self, messages) -> Intent:  # noqa: ANN001
        raise httpx.ConnectError("llm gateway unreachable")

    async def summarize(self, **kwargs) -> str:  # noqa: ANN003
        return ""


class _ObserveThenFailLLM:
    """首次 plan 要求观测，第二次 plan（re-plan）抛——复现 CONTEXT_COLLECTED 期失败。"""

    def __init__(self) -> None:
        self.calls = 0

    async def plan(self, messages) -> Intent:  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            return Intent.model_validate(
                {
                    "intent": "check disk",
                    "confidence": 0.9,
                    "need_observation": True,
                    "candidate_tools": [{"name": "disk.usage", "args": {}}],
                    "risk_hint": "low",
                    "justification": "observe first",
                }
            )
        raise httpx.ConnectError("llm gateway unreachable on re-plan")

    async def summarize(self, **kwargs) -> str:  # noqa: ANN003
        return ""


def _build(llm) -> tuple[Orchestrator, _Audit, _Events]:  # noqa: ANN001
    from backend.app.contracts.policy import PolicyVerdict
    from backend.app.contracts.tool import ToolSpec
    from backend.app.contracts.untrusted import ToolResult
    from backend.app.mcp.gateway import MCPGateway
    from backend.app.mcp.registry import ToolRegistry

    spec = ToolSpec(
        name="disk.usage",
        description="d",
        risk="R0",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        requires_roles=["operator"],
        reversible=True,
    )

    class _Policy:
        def evaluate(self, tool):  # noqa: ANN001
            return PolicyVerdict(
                decision="allow",
                final_risk="R0",
                matched_rules=[],
                reason="ok",
                approval_required=False,
            )

    class _Executor:
        async def execute(self, tool):  # noqa: ANN001
            return ToolResult(tool=tool.name, args=tool.args, exit_code=0, stdout_truncated="ok")

    audit, events = _Audit(), _Events()
    gateway = MCPGateway(ToolRegistry([spec]), _Policy(), _Executor())
    orch = Orchestrator(llm=llm, gateway=gateway, audit=audit, events=events)
    return orch, audit, events


def test_f1_plan_failure_reaches_failed_terminal() -> None:
    """F-1: RECEIVED 期 plan 失败必须收敛到 FAILED，不能停在 RECEIVED。"""
    orch, _, _ = _build(_FailingPlanLLM())

    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))

    assert is_terminal(end), f"F-1: 规划失败后停在非终态 {end.value}——trace 永不闭合"
    assert end is State.FAILED, f"F-1: 应为 FAILED，实际 {end.value}"


def test_f2_replan_failure_reaches_failed_terminal() -> None:
    """F-2: CONTEXT_COLLECTED 期 re-plan 失败同样必须收敛到 FAILED。"""
    orch, _, _ = _build(_ObserveThenFailLLM())

    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))

    assert is_terminal(end), f"F-2: re-plan 失败后停在非终态 {end.value}——trace 永不闭合"
    assert end is State.FAILED, f"F-2: 应为 FAILED，实际 {end.value}"


def test_f3_failed_phase_audited() -> None:
    """F-3: 必须留下 phase=FAILED 的审计——retention 终态闸只认 phase。

    状态机走到 FAILED 但审计没记 FAILED，retention 照样把它当 in-flight，
    ①号后果原样存在。故这条断言与 F-1 不重复。
    """
    orch, audit, _ = _build(_FailingPlanLLM())

    asyncio.run(orch.run([{"role": "user", "content": "x"}]))

    assert State.FAILED.value in audit.phases(), (
        f"F-3: 审计缺 FAILED phase，retention 仍会视其为 in-flight："
        f"实际 phases={audit.phases()}"
    )


def test_f4_planning_failure_not_recorded_as_security_rejection() -> None:
    """F-4: 系统故障不得混进 REJECTED 的安全拒绝语义。

    把 LLM 不可用记成"拒绝"会污染安全叙事——审计读者会以为触发了策略拦截。
    """
    orch, audit, events = _build(_FailingPlanLLM())

    asyncio.run(orch.run([{"role": "user", "content": "x"}]))

    assert State.REJECTED.value not in audit.phases(), "F-4: 规划失败被记成了 REJECTED"
    assert "rejected" not in events.types(), "F-4: 规划失败 emit 了 rejected 事件"
