"""之七十五 M-2: S9 脱敏输入侧对称（不只在输出侧扫）。

不对称的实际后果：工具 stdout 里的凭据（journalctl 抓到的连接串、config 快照里的
密码字段…）此前会**原样发给外部 LLM 网关**。输出侧的 scan_and_redact 只保证不回显
给前端，管不住已经出网的那一份——凭据一旦出网就追不回来了。

  M2-1 orchestrator：送进 llm.summarize 的 tool_results 已脱敏
  M2-2 orchestrator：结构化字段（tool/args/exit_code）不被误伤
  M2-3 orchestrator：不改调用方原对象（脱敏发生在副本上）
  M2-4 RCA 路径：送进 llm.summarize 的 evidence 已脱敏（同口径）
  M2-5 输出侧原有脱敏仍在（M-2 是补输入侧，不是搬走输出侧）
"""

from __future__ import annotations

import asyncio
import json
from unittest import mock

from backend.app.contracts.untrusted import ToolResult

_SECRET_LINE = "connecting with password=hunter2-super-secret to db"


def _result(stdout: str) -> ToolResult:
    return ToolResult(
        tool="log.journal_query",
        args={"unit": "app"},
        exit_code=0,
        stdout_truncated=stdout,
    )


def _build_orch(summary: str | None = "ok"):
    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.audit import SqliteAuditSink
    from backend.app.llm.adapter import LLMAdapter

    llm = mock.MagicMock(spec=LLMAdapter)
    llm.summarize = mock.AsyncMock(return_value=summary)
    orch = Orchestrator(
        trace_id="m2",
        audit=SqliteAuditSink(":memory:"),
        llm=llm,
        events=mock.MagicMock(),
        gateway=mock.MagicMock(),
    )
    return orch, llm


def test_m2_1_summarize_input_is_redacted() -> None:
    """M2-1: llm.summarize 收到的 tool_results 不得含裸凭据。"""
    orch, llm = _build_orch()
    results = [_result(_SECRET_LINE)]

    asyncio.run(orch._emit_natural_language(results))

    llm.summarize.assert_awaited_once()
    sent = json.dumps(llm.summarize.await_args.kwargs["tool_results"], ensure_ascii=False)
    assert "hunter2-super-secret" not in sent, "M2-1: 凭据原样出网到 LLM 网关"
    assert "REDACTED" in sent, "M2-1: 应已 redact"


def test_m2_2_structured_fields_not_damaged() -> None:
    """M2-2: 只脱敏 stdout 类自由文本，结构化字段保持原样（不误伤）。"""
    orch, llm = _build_orch()
    asyncio.run(orch._emit_natural_language([_result(_SECRET_LINE)]))

    sent = llm.summarize.await_args.kwargs["tool_results"][0]
    assert sent["tool"] == "log.journal_query"
    assert sent["args"] == {"unit": "app"}
    assert sent["exit_code"] == 0


def test_m2_3_caller_objects_untouched() -> None:
    """M2-3: 脱敏在副本上做，不得改调用方持有的 ToolResult（证据链另有用途）。"""
    orch, _llm = _build_orch()
    results = [_result(_SECRET_LINE)]

    asyncio.run(orch._emit_natural_language(results))

    assert results[0].stdout_truncated == _SECRET_LINE, "M2-3: 不应就地改写调用方对象"


def test_m2_4_rca_path_input_is_redacted() -> None:
    """M2-4: RCA 改写路径的 evidence 同样脱敏（与主链路同口径）。"""
    from backend.app.agent.rca_summary_llm import llm_rewrite_summary
    from backend.app.llm.adapter import LLMAdapter

    llm = mock.MagicMock(spec=LLMAdapter)
    llm.summarize = mock.AsyncMock(return_value="磁盘占用过高")
    evidence = [{"tool": "disk.usage", "stdout_truncated": _SECRET_LINE, "exit_code": 0}]

    asyncio.run(llm_rewrite_summary(llm, evidence, {"summary": "playbook 原文"}))

    kwargs = llm.summarize.await_args.kwargs
    sent = json.dumps([kwargs["tool_results"], kwargs["evidence"]], ensure_ascii=False)
    assert "hunter2-super-secret" not in sent, "M2-4: RCA 路径凭据原样出网"
    assert evidence[0]["stdout_truncated"] == _SECRET_LINE, "M2-4: 不应就地改写入参"


def test_m2_5_output_side_redaction_still_active() -> None:
    """M2-5: 输出侧脱敏未被搬走——LLM 幻觉/复述带出的凭据仍要拦。

    输入输出两侧职责不同：输入侧防"凭据出网"，输出侧防"LLM 生成的文本里带凭据"。
    M-2 是补前者，不得以此弱化后者。
    """
    orch, _llm = _build_orch(summary=f"总结：{_SECRET_LINE}")
    sink = mock.MagicMock()
    orch._events = sink

    asyncio.run(orch._emit_natural_language([_result("clean output")]))

    emitted = [c.args[0] for c in sink.emit.call_args_list]
    nl = [e for e in emitted if e.type == "natural_language"]
    assert nl, "M2-5: 应 emit natural_language"
    assert "hunter2-super-secret" not in nl[0].data["text"], "M2-5: 输出侧脱敏失效"
    assert nl[0].data["sensitive_filtered"] is True
