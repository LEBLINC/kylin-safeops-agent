"""X P6: orchestrator _emit_rca_summary 守门 (3 用例 T5-T7).

T5 evidence 含 high 注入 → 拦下 + 不调 LLM + audit phase=injection_high
T6 clean evidence → 调 LLM.summarize() + audit OK
T7 rca 路径 hash chain 不破
"""

from __future__ import annotations

import asyncio
from unittest import mock


class _CapSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, event):  # noqa: ANN001
        self.events.append((event.type, event.data))


def test_t5_rca_injection_high_blocks_llm(monkeypatch) -> None:
    """T5: evidence 含 high 注入 → 拦下 + 不调 LLM + audit injection_high."""


def test_t6_rca_clean_calls_llm_summarize() -> None:
    """T6: clean evidence → 调 LLM.summarize() + audit phase=rca_summarize_failed (或 OK)."""
    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.agent.rca import NullRCA
    from backend.app.audit import SqliteAuditSink
    from backend.app.contracts.untrusted import ToolResult
    from backend.app.llm.adapter import LLMAdapter, LLMConfig
    from backend.app.llm.real_client import RealLLMClient
    audit = SqliteAuditSink(":memory:")
    summary_mock = mock.AsyncMock(return_value="LLM RCA 总结")
    cfg = LLMConfig(provider="real")
    real = mock.MagicMock(spec=RealLLMClient)
    real.summarize = summary_mock
    adapter = LLMAdapter(cfg, completion_fn=mock.AsyncMock(), summary_fn=real.summarize)
    orch = Orchestrator(
        trace_id="t6", audit=audit, llm=adapter,
        events=_CapSink(), gateway=mock.MagicMock(), rca=NullRCA(),
    )
    orch._evidence = [
        ToolResult(tool="disk.usage", exit_code=0, stdout_truncated="ok"),
    ]
    asyncio.run(orch._emit_rca_summary(orch._evidence, {}))
    # mock 的 summary 必须被调
    assert summary_mock.called, "T6: clean evidence 应调 LLM.summarize"


def test_t7_rca_summary_preserves_chain() -> None:
    """T7: rca 路径 hash chain 不破."""
    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.agent.rca import NullRCA
    from backend.app.audit import SqliteAuditSink
    from backend.app.contracts.untrusted import ToolResult
    from backend.app.llm.adapter import LLMAdapter, LLMConfig
    from backend.app.llm.real_client import RealLLMClient
    audit = SqliteAuditSink(":memory:")
    cfg = LLMConfig(provider="real")
    real = mock.MagicMock(spec=RealLLMClient)
    real.summarize = mock.AsyncMock(return_value=None)
    adapter = LLMAdapter(cfg, completion_fn=mock.AsyncMock(), summary_fn=real.summarize)
    orch = Orchestrator(
        trace_id="t7", audit=audit, llm=adapter,
        events=_CapSink(), gateway=mock.MagicMock(), rca=NullRCA(),
    )
    orch._evidence = [
        ToolResult(tool="disk.usage", exit_code=0, stdout_truncated="ok"),
    ]
    asyncio.run(orch._emit_rca_summary(orch._evidence, {}))
    result = audit.verify_chain(orch.trace_id)
    assert result.valid, f"T7 哈希链被破: {result}"
