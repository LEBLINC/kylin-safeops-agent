"""B6 L-C6 fallback test - placeholder."""

from __future__ import annotations

import asyncio
from unittest import mock


def test_t3_summarize_failure_no_natural_language_event() -> None:
    """T3: 验 _emit_natural_language 内 except 路径不调 self._emit('natural_language').

    简化版:直接调 _emit_natural_language, mock llm.summarize raise TimeoutException,
    verify events list 不含 type='natural_language'。
    """
    import httpx

    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.audit import SqliteAuditSink
    from backend.app.llm.adapter import LLMConfig

    # build minimal orchestrator
    LLMConfig(provider="real", base_url="http://mock")
    llm = mock.MagicMock()
    audit = SqliteAuditSink(":memory:")

    captured_events: list[dict] = []

    async def _capture_summarize(**kwargs):
        raise httpx.TimeoutException("LLM summarize timeout", request=None)

    llm.summarize = _capture_summarize

    class _FakeEvents:
        def emit(self, evt):
            captured_events.append(evt)

    orch = Orchestrator(llm=llm, gateway=mock.MagicMock(), audit=audit, events=_FakeEvents())

    # 调 _emit_natural_language 真路径
    from backend.app.contracts.untrusted import ToolResult

    asyncio.run(
        orch._emit_natural_language(
            [
                ToolResult(tool="disk.usage", exit_code=0, stdout_truncated="ok"),
            ]
        )
    )

    # 不应 emit 'natural_language' 事件
    nl_events = [e for e in captured_events if getattr(e, "type", None) == "natural_language"]
    assert len(nl_events) == 0, (
        f"T3 失败: summarize 失败仍 emit {len(nl_events)} natural_language 事件; "
        "应静默 (前端零污染)"
    )
    # fallback_count 应 == 1
    assert orch._fallback_count == 1, f"T3 期望 fallback_count=1, got {orch._fallback_count}"


# ---- T4: metrics fallback_count == 5 after 5 fails ----
def test_t4_summarize_failure_increments_metrics() -> None:
    """T4: 5 次 summarize 失败 → orchestrator._fallback_count == 5."""
    import httpx

    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.audit import SqliteAuditSink
    from backend.app.contracts.untrusted import ToolResult
    from backend.app.llm.adapter import LLMConfig

    LLMConfig(provider="real", base_url="http://mock")
    llm = mock.MagicMock()
    audit = SqliteAuditSink(":memory:")

    async def _fail_summarize(**kwargs):
        raise httpx.TimeoutException("x", request=None)

    llm.summarize = _fail_summarize
    orch = Orchestrator(llm=llm, gateway=mock.MagicMock(), audit=audit, events=mock.MagicMock())

    async def _drive():
        for _ in range(5):
            await orch._emit_natural_language(
                [
                    ToolResult(tool="x", exit_code=0, stdout_truncated="y"),
                ]
            )

    asyncio.run(_drive())
    assert orch._fallback_count == 5, f"T4 期望 fallback_count=5, got {orch._fallback_count}"
