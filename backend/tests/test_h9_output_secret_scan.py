"""C4（阶段6 第二梯队 H9 输出侧收尾）守门测试。

覆盖：
  T1 summary 含疑似凭据 → redact + sensitive_filtered=True
  T2 干净 summary → 原文不变 + sensitive_filtered=False
  T3 orchestrator._emit_natural_language 端到端：LLM summary 含凭据模式
     → emit 的 natural_language 事件 text 已 redact，sensitive_filtered=True
"""

from __future__ import annotations

import asyncio
from unittest import mock

from backend.app.agent.secret_scan import scan_and_redact


def test_t1_summary_with_credential_pattern_redacted() -> None:
    """T1: summary 含 api_key=... 模式 → redact 命中 + sensitive_filtered=True。"""
    text = "已完成磁盘检查，顺便发现配置里 api_key=sk-abcdef123456 需要轮换。"
    redacted, hit = scan_and_redact(text)
    assert hit is True, "T1 期望命中凭据模式"
    assert "sk-abcdef123456" not in redacted, "T1 期望明文凭据被替换"
    assert "***REDACTED***" in redacted


def test_t2_clean_summary_untouched() -> None:
    """T2: 干净 summary（无凭据模式）→ 原文不变 + sensitive_filtered=False。"""
    text = "已完成:disk.usage,process.list"
    redacted, hit = scan_and_redact(text)
    assert hit is False, "T2 期望未命中"
    assert redacted == text, "T2 期望原文不变"


def test_t3_orchestrator_emit_natural_language_redacts_summary() -> None:
    """T3: orchestrator._emit_natural_language 端到端 — LLM summary 含凭据模式
    → emit 的 natural_language 事件 text 已 redact，sensitive_filtered=True。
    """
    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.audit import SqliteAuditSink
    from backend.app.contracts.untrusted import ToolResult

    llm = mock.MagicMock()

    async def _fake_summarize(**kwargs):
        return "已完成:检测到 password: hunter2 需要立即修改。"

    llm.summarize = _fake_summarize
    audit = SqliteAuditSink(":memory:")

    captured_events: list = []

    class _FakeEvents:
        def emit(self, evt):
            captured_events.append(evt)

    orch = Orchestrator(llm=llm, gateway=mock.MagicMock(), audit=audit, events=_FakeEvents())

    asyncio.run(
        orch._emit_natural_language(
            [ToolResult(tool="disk.usage", exit_code=0, stdout_truncated="ok")]
        )
    )

    nl_events = [e for e in captured_events if getattr(e, "type", None) == "natural_language"]
    assert len(nl_events) == 1, "T3 期望恰好 1 条 natural_language 事件"
    data = nl_events[0].data
    assert data["sensitive_filtered"] is True, "T3 期望 sensitive_filtered=True（死标志变活）"
    assert "hunter2" not in data["text"], "T3 期望明文凭据被替换"
    assert "***REDACTED***" in data["text"]


def test_t4_orchestrator_emit_natural_language_clean_summary_false() -> None:
    """T4: 干净 summary → sensitive_filtered=False（回归：不误报）。"""
    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.audit import SqliteAuditSink
    from backend.app.contracts.untrusted import ToolResult

    llm = mock.MagicMock()

    async def _fake_summarize(**kwargs):
        return "已完成:disk.usage"

    llm.summarize = _fake_summarize
    audit = SqliteAuditSink(":memory:")
    captured_events: list = []

    class _FakeEvents:
        def emit(self, evt):
            captured_events.append(evt)

    orch = Orchestrator(llm=llm, gateway=mock.MagicMock(), audit=audit, events=_FakeEvents())

    asyncio.run(
        orch._emit_natural_language(
            [ToolResult(tool="disk.usage", exit_code=0, stdout_truncated="ok")]
        )
    )

    nl_events = [e for e in captured_events if getattr(e, "type", None) == "natural_language"]
    assert len(nl_events) == 1
    assert nl_events[0].data["sensitive_filtered"] is False
    assert nl_events[0].data["text"] == "已完成:disk.usage"
