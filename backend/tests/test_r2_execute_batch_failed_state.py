"""之七十五 R-2: _execute_batch 故障分支补审计 + FAILED 终态 守门测试。

R-2 前，_execute_batch 的两个故障分支（gateway 抛异常 / gateway 二次过闸拦下）
只 emit error 就 return，留下三个洞：
  ① 审计链缺该条——事后无从判定 trace 因何中断
  ② 状态永久停在 EXECUTING——retention 终态闸把它当 in-flight 永不清理
  ③ SSE 靠 runner 通用兜底关闭，而非终态语义收尾

本用例锁死修复后的行为（两分支同构）：
  R2-1 gateway 抛异常 → 审计链含该记录（phase=FAILED）+ verify_chain valid
       + 状态 FAILED + emit error
  R2-2 gateway 二次过闸拦下（executed=False）→ 同构
  R2-3 runner._finalize 把 FAILED 视作终态（mark_done + bus.close，SSE 正常关闭）
  R2-4 异常消息经 S9 scan_and_redact——凭据不进审计、不进 SSE
  R2-5 契约6 stream.py 零改动：终态信号复用既有 error 事件，未新增 EventType，
       且不得把系统故障伪装成 rejected（安全拒绝语义不被污染）
"""

from __future__ import annotations

import asyncio
import json
from unittest import mock

from backend.app.agent.state_machine import State
from backend.app.contracts.intent import CandidateTool
from backend.app.mcp.gateway import CallOutcome

_TRACE = "r2-test"


class _CapSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, evt) -> None:  # noqa: ANN001
        self.events.append((evt.type, evt.data))


def _build(gateway_call):  # noqa: ANN001
    """造一个已进到"待执行整批"状态的 orchestrator（绕开 LLM 规划）。"""
    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.audit import SqliteAuditSink

    audit = SqliteAuditSink(":memory:")
    sink = _CapSink()
    gw = mock.MagicMock()
    gw.call = gateway_call
    orch = Orchestrator(
        trace_id=_TRACE,
        audit=audit,
        llm=mock.MagicMock(),
        events=sink,
        gateway=gw,
    )
    # _execute_batch 的前置：状态须为 POLICY_CHECKED（EXECUTING 的合法前驱），批次非空
    orch.state = State.POLICY_CHECKED
    orch._batch = [CandidateTool(name="disk.usage", args={})]
    return orch, audit, sink


def _audit_rows(audit, phase: str):  # noqa: ANN001
    return audit._conn.execute(
        "SELECT seq, phase, payload FROM audit_records WHERE trace_id=? AND phase=?",
        (_TRACE, phase),
    ).fetchall()


def test_r2_1_gateway_exception_audits_and_enters_failed() -> None:
    """R2-1: gateway.call 抛异常 → phase=FAILED 审计 + 链 valid + 状态 FAILED + error 事件。"""
    orch, audit, sink = _build(mock.AsyncMock(side_effect=RuntimeError("sandbox unreachable")))

    state = asyncio.run(orch._execute_batch(approved=False))

    assert state is State.FAILED, f"R2-1: 应进 FAILED 终态，实际 {state}"
    rows = _audit_rows(audit, "FAILED")
    assert rows, "R2-1: 审计链应含 phase=FAILED 记录"
    payload = json.loads(rows[0]["payload"])
    assert payload["cause"] == "gateway_exception"
    assert payload["tool"] == "disk.usage"
    assert payload["failed_phase"] == "EXECUTING", "R2-1: 应记录故障发生时所处阶段"
    assert "sandbox unreachable" in payload["error_message"]

    assert audit.verify_chain(_TRACE).valid, "R2-1: S3 哈希链必须仍 valid"

    errors = [d for t, d in sink.events if t == "error"]
    assert len(errors) == 1, f"R2-1: 应 emit 恰好一条 error，实际 {sink.events!r}"
    assert errors[0]["phase"] == "EXECUTING"


def test_r2_2_gateway_blocked_audits_and_enters_failed() -> None:
    """R2-2: gateway 二次过闸拦下（executed=False）→ 与异常分支同构。"""
    orch, audit, sink = _build(
        mock.AsyncMock(return_value=CallOutcome(executed=False, reason="policy re-check deny"))
    )

    state = asyncio.run(orch._execute_batch(approved=False))

    assert state is State.FAILED, f"R2-2: 应进 FAILED 终态，实际 {state}"
    rows = _audit_rows(audit, "FAILED")
    assert rows, "R2-2: 审计链应含 phase=FAILED 记录"
    payload = json.loads(rows[0]["payload"])
    assert payload["cause"] == "gateway_blocked"
    assert payload["tool"] == "disk.usage"
    assert "policy re-check deny" in payload["error_message"]

    assert audit.verify_chain(_TRACE).valid, "R2-2: S3 哈希链必须仍 valid"
    assert [t for t, _ in sink.events].count("error") == 1


def test_r2_3_runner_finalize_closes_sse_on_failed() -> None:
    """R2-3: runner._finalize 把 FAILED 当终态——mark_done + bus.close（SSE 不挂死）。"""
    from backend.app.api.event_bus import EventBus
    from backend.app.api.runner import _finalize
    from backend.app.api.session_registry import SessionRegistry

    bus = mock.MagicMock(spec=EventBus)
    registry = mock.MagicMock(spec=SessionRegistry)

    _finalize(State.FAILED, bus, registry, _TRACE)

    registry.mark_done.assert_called_once_with(_TRACE)
    bus.close.assert_called_once_with(_TRACE)


def test_r2_4_error_message_redacted_by_s9() -> None:
    """R2-4: 异常消息经 scan_and_redact——凭据既不进审计也不进 SSE。"""
    secret = "connect failed: password=hunter2-super-secret"
    orch, audit, sink = _build(mock.AsyncMock(side_effect=RuntimeError(secret)))

    asyncio.run(orch._execute_batch(approved=False))

    payload = json.loads(_audit_rows(audit, "FAILED")[0]["payload"])
    assert "hunter2-super-secret" not in payload["error_message"], "R2-4: 审计不得留裸凭据"
    assert payload["sensitive_filtered"] is True

    errors = [d for t, d in sink.events if t == "error"]
    assert "hunter2-super-secret" not in errors[0]["message"], "R2-4: SSE 不得推裸凭据"


def test_r2_5_no_new_event_type_and_not_disguised_as_rejected() -> None:
    """R2-5: 终态信号复用 error 事件；契约6 EventType 13 值不变，且不发 rejected。

    明确否决 rejected(cause="internal_error")——系统故障混入安全拒绝语义会污染
    核心安全叙事（rejected 的 cause 三值 injection/policy_deny/user_reject 不动）。
    """
    from typing import get_args

    from backend.app.contracts.stream import EventType

    assert len(get_args(EventType)) == 13, "R2-5: 契约6 EventType 必须仍是 13 值（stream.py 零改动）"

    orch, _audit, sink = _build(mock.AsyncMock(side_effect=RuntimeError("boom")))
    asyncio.run(orch._execute_batch(approved=False))

    types = [t for t, _ in sink.events]
    assert "rejected" not in types, "R2-5: 系统故障不得伪装成 rejected（安全拒绝语义不被污染）"
    assert "error" in types
    assert set(types) <= set(get_args(EventType)), f"R2-5: 出现契约外事件类型 {types!r}"
