"""D3-b orchestrator 测试：分支驱动、逐点 emit/audit、哈希链、异常→error。

全部用 fake 协作者 + 注入 completion_fn 的真 LLMAdapter，不触网、不执行真命令。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from backend.app.agent.orchestrator import Orchestrator, most_restrictive
from backend.app.agent.state_machine import State
from backend.app.contracts.audit import GENESIS_HASH, AuditRecord, compute_curr_hash
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.stream import StreamEvent
from backend.app.contracts.untrusted import ToolResult
from backend.app.llm.adapter import LLMAdapter

# ---- fakes ---------------------------------------------------------------


def _intent_json(*, need_observation: bool = False, tools: list[dict] | None = None) -> str:
    return json.dumps(
        {
            "intent": "clean_system_garbage",
            "confidence": 0.9,
            "need_observation": need_observation,
            "candidate_tools": tools if tools is not None else [{"name": "disk.usage", "args": {}}],
            "risk_hint": "medium",
            "justification": "test",
        }
    )


def _llm_returning(output: str) -> LLMAdapter:
    async def fn(messages):  # noqa: ANN001
        return output

    return LLMAdapter(completion_fn=fn)


class FakePolicy:
    def __init__(self, verdict: PolicyVerdict) -> None:
        self._verdict = verdict

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return self._verdict


class FakeExecutor:
    def __init__(self, *, exit_code: int = 0, raises: Exception | None = None) -> None:
        self.exit_code = exit_code
        self.raises = raises
        self.calls: list[CandidateTool] = []

    async def execute(self, tool: CandidateTool) -> ToolResult:
        self.calls.append(tool)
        if self.raises is not None:
            raise self.raises
        return ToolResult(
            tool=tool.name, args=tool.args, exit_code=self.exit_code, stdout_truncated="out"
        )


class FakeAudit:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


class FakeEvents:
    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    def emit(self, event: StreamEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type for e in self.events]


def _verdict(decision, *, role=None, risk="R1") -> PolicyVerdict:  # noqa: ANN001
    return PolicyVerdict(
        decision=decision,
        final_risk=risk,
        matched_rules=["rule.test"],
        reason="test",
        approval_required=(decision == "confirm"),
        approval_role=role,
    )


def _build(llm, verdict, **exec_kw):  # noqa: ANN001
    audit, events = FakeAudit(), FakeEvents()
    orch = Orchestrator(
        llm=llm,
        policy=FakePolicy(verdict),
        executor=FakeExecutor(**exec_kw),
        audit=audit,
        events=events,
        trace_id="trace-test",
    )
    return orch, audit, events


# ---- helpers -------------------------------------------------------------


def _assert_chain_intact(audit: FakeAudit) -> None:
    """逐条复算哈希链，验证连续且可复算。"""
    prev = GENESIS_HASH
    for i, rec in enumerate(audit.records):
        assert rec.seq == i
        assert rec.prev_hash == prev
        assert rec.curr_hash == compute_curr_hash(prev, rec.payload)
        prev = rec.curr_hash


# ---- tests ---------------------------------------------------------------


def test_most_restrictive_picks_deny() -> None:
    v = most_restrictive([_verdict("allow"), _verdict("confirm"), _verdict("deny")])
    assert v.decision == "deny"


def test_allow_runs_full_chain_to_finished() -> None:
    orch, audit, events = _build(_llm_returning(_intent_json()), _verdict("allow"))
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}], user_intent="clean"))
    assert end is State.FINISHED
    _assert_chain_intact(audit)
    # 逐点 emit 判定：RECEIVED/REJECTED/FINISHED 无独立前端事件
    assert "intent_parsed" in events.types()
    assert "plan_generated" in events.types()
    assert "policy_verdict" in events.types()
    assert "executing" in events.types()
    assert "tool_result" in events.types()
    assert "verified" in events.types()


def test_observation_branch_emits_observation() -> None:
    orch, _audit, events = _build(
        _llm_returning(_intent_json(need_observation=True)), _verdict("allow")
    )
    asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert "observation" in events.types()


def test_deny_goes_rejected_no_execution() -> None:
    orch, audit, events = _build(_llm_returning(_intent_json()), _verdict("deny"))
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.REJECTED
    assert orch._executor.calls == []  # type: ignore[attr-defined]
    assert "executing" not in events.types()
    _assert_chain_intact(audit)


def test_empty_candidates_denied() -> None:
    orch, _audit, _events = _build(_llm_returning(_intent_json(tools=[])), _verdict("allow"))
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.REJECTED  # 无候选合成 deny


def test_confirm_pauses_then_resume_approved() -> None:
    orch, audit, events = _build(_llm_returning(_intent_json()), _verdict("confirm", role="admin"))
    paused = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert paused is State.WAIT_APPROVAL
    assert "await_approval" in events.types()
    end = asyncio.run(orch.resume(approved=True))
    assert end is State.FINISHED
    _assert_chain_intact(audit)


def test_confirm_then_resume_rejected() -> None:
    orch, audit, _events = _build(_llm_returning(_intent_json()), _verdict("confirm", role="admin"))
    asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    end = asyncio.run(orch.resume(approved=False))
    assert end is State.REJECTED
    assert orch._executor.calls == []  # type: ignore[attr-defined]
    _assert_chain_intact(audit)


def test_resume_outside_wait_approval_raises() -> None:
    orch, _audit, _events = _build(_llm_returning(_intent_json()), _verdict("allow"))
    with pytest.raises(RuntimeError):
        asyncio.run(orch.resume(approved=True))


def test_execution_failure_walks_full_chain_via_exit_code() -> None:
    """方案 B：执行失败(exit_code!=0)仍走 EXECUTED→VERIFIED→FINISHED，由 VERIFIED 判定。"""
    orch, audit, events = _build(_llm_returning(_intent_json()), _verdict("allow"), exit_code=1)
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.FINISHED
    verified = [e for e in events.events if e.type == "verified"][0]
    assert "non-zero" in verified.data["summary"]
    _assert_chain_intact(audit)


def test_executor_exception_emits_error_and_stops() -> None:
    orch, _audit, events = _build(
        _llm_returning(_intent_json()), _verdict("allow"), raises=OSError("boom")
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.EXECUTING  # 停在执行态，未推进
    assert "error" in events.types()


def test_llm_network_error_emits_error_and_stops() -> None:
    async def fn(messages):  # noqa: ANN001
        raise httpx.ConnectError("no route")

    orch, _audit, events = _build(LLMAdapter(completion_fn=fn), _verdict("allow"))
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.RECEIVED  # 规划即失败，停在初态
    assert "error" in events.types()


def test_tool_result_forced_untrusted() -> None:
    """结果闸：即使 Executor 返回 is_untrusted=False 也被强制改 True。"""

    class SneakyExecutor:
        async def execute(self, tool: CandidateTool) -> ToolResult:
            return ToolResult.model_construct(
                tool=tool.name,
                args={},
                exit_code=0,
                stdout_truncated="",
                is_untrusted=False,
                wrap_token="<<UNTRUSTED_TOOL_OUTPUT>>",
            )

    audit, events = FakeAudit(), FakeEvents()
    orch = Orchestrator(
        llm=_llm_returning(_intent_json()),
        policy=FakePolicy(_verdict("allow")),
        executor=SneakyExecutor(),
        audit=audit,
        events=events,
        trace_id="t",
    )
    asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    tr = [e for e in events.events if e.type == "tool_result"][0]
    assert tr.data["result"]["is_untrusted"] is True


def test_audit_decision_key_only_holds_valid_decisions() -> None:
    """审计 payload 的 decision 键只能出现契约3 Decision 值，不被阶段语义污染。"""
    valid = {"allow", "deny", "confirm"}
    for verdict in (_verdict("allow"), _verdict("deny"), _verdict("confirm", role="admin")):
        _orch, audit, _events = _build(_llm_returning(_intent_json()), verdict)
        asyncio.run(_orch.run([{"role": "user", "content": "x"}]))
        if _orch.state is State.WAIT_APPROVAL:
            asyncio.run(_orch.resume(approved=True))
        for rec in audit.records:
            if "decision" in rec.payload:
                assert rec.payload["decision"] in valid
