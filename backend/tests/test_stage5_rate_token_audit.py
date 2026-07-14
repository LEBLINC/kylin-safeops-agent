"""5.3 rate-limit + token-cap 接审计守门 (B5 P4 收口).

覆盖 4 用例 (T8 + T9-T11):
  T8  mock _RateLimiter raise → audit 落库
  T9  rate_limited path → audit phase="rate_limited"
  T10 token_cap path → audit phase="token_cap_exceeded"
  T11 token_cap path emit natural_language event with synthetic=true
"""

from __future__ import annotations

import asyncio
from unittest import mock


class _CapSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, type_, data):  # noqa: ANN001
        self.events.append((type_, data))


async def _drive_natural_language(orch, tools):
    """直接调 _emit_natural_language 真路径 (跳过 plan/execute)."""
    from backend.app.contracts.untrusted import ToolResult

    results = [ToolResult(tool=t, exit_code=0, stdout_truncated="ok") for t in tools]
    await orch._emit_natural_language(results)


def _orch(audit, summary_fn):
    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.llm.adapter import LLMAdapter, LLMConfig

    adapter = LLMAdapter(LLMConfig(provider="real"), completion_fn=mock.AsyncMock())
    adapter._summary_fn = summary_fn
    sink = _CapSink()
    gw = mock.MagicMock()
    orch = Orchestrator(trace_id="t9", audit=audit, llm=adapter, events=sink, gateway=gw)
    orch._emit = lambda t, d: sink.events.append((t, d))  # type: ignore[method-assign]
    return orch, sink


# ---- T8: rate_limited 落库 ----


def test_t8_rate_limit_raises_orchestrator_audit() -> None:
    from backend.app.audit import SqliteAuditSink

    audit = SqliteAuditSink(":memory:")
    rate_limited = mock.AsyncMock(side_effect=RuntimeError("rate_limited (3/min)"))
    orch, _ = _orch(audit, rate_limited)
    asyncio.run(_drive_natural_language(orch, ["x"]))
    # 状态保持 RECEIVED (S8 fail-closed 不杀)
    assert orch.state.value == "RECEIVED", f"T8: 期望 RECEIVED, got {orch.state.value}"


# ---- T9: phase="rate_limited" ----


def test_t9_rate_limit_phase_distinct() -> None:
    from backend.app.audit import SqliteAuditSink

    audit = SqliteAuditSink(":memory:")
    rate_limited = mock.AsyncMock(side_effect=RuntimeError("rate_limited (3/min)"))
    orch, _ = _orch(audit, rate_limited)
    asyncio.run(_drive_natural_language(orch, ["x"]))
    rows = audit._conn.execute(
        "SELECT phase FROM audit_records WHERE trace_id = ?", (orch.trace_id,)
    ).fetchall()
    phases = [r[0] for r in rows]
    assert "rate_limited" in phases, f"T9 期望 phase=rate_limited, got {phases}"


# ---- T10: phase="token_cap_exceeded" ----


def test_t10_token_cap_phase_distinct() -> None:
    from backend.app.audit import SqliteAuditSink

    audit = SqliteAuditSink(":memory:")
    token_cap = mock.AsyncMock(side_effect=RuntimeError("token_cap_exceeded: 100000"))
    orch, _ = _orch(audit, token_cap)
    asyncio.run(_drive_natural_language(orch, ["x"]))
    rows = audit._conn.execute(
        "SELECT phase FROM audit_records WHERE trace_id = ?", (orch.trace_id,)
    ).fetchall()
    phases = [r[0] for r in rows]
    assert "token_cap_exceeded" in phases, f"T10 期望 phase=token_cap_exceeded, got {phases}"


# ---- T11: token_cap emit natural_language synthetic=true ----


def test_t11_token_cap_emits_natural_language_synthetic() -> None:
    from backend.app.audit import SqliteAuditSink

    audit = SqliteAuditSink(":memory:")
    token_cap = mock.AsyncMock(side_effect=RuntimeError("token_cap_exceeded: 100000"))
    orch, sink = _orch(audit, token_cap)
    asyncio.run(_drive_natural_language(orch, ["x"]))
    nl_events = [(t, d) for t, d in sink.events if t == "natural_language"]
    assert (
        len(nl_events) == 1
    ), f"T11: token_cap 应 emit 1 个 natural_language (synthetic), got {len(nl_events)}"
    _, payload = nl_events[0]
    assert payload.get("synthetic") is True, f"T11 期望 synthetic=true, got {payload}"
    assert (
        payload.get("fallback") == "token_cap_exceeded"
    ), f"T11 期望 fallback=token_cap_exceeded, got {payload}"
