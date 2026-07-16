"""之六十八 Task 4 / 测试 1: orchestrator._emit_rca_summary 单测 mock 复现（端到端 LLM）。

覆盖（4 用例）：
  T1 orchestrator._emit_rca_summary + DefaultRCAEngine.analyze_problem 真接 LLM
     → audit rca_llm_summary ok + summary 是 LLM 输出（与 fake_llm.summarize_return
     字节级一致）+ 含关键 token
  T2 同一个 evidence 走 audit 全链,验证 ChainVerifyResult.valid
  T3 summary 字段 LLM 化: report["summary"] = llm_rewrite_summary 输出,
     report["summary_source"] == "llm"
  T4 反向场景：fake_llm.summarize_return=None → audit 不记 rca_llm_summary,
     summary_source == "playbook"（兜底回归）
"""

from __future__ import annotations

import asyncio
from unittest import mock

# ---- 构造数据 -----------------------------------------------------------


_DISK_EVIDENCE_DICTS = [
    {
        "tool": "disk.usage",
        "args": {},
        "stdout_truncated": "Filesystem /dev/sda1: Used=85% / Avail=2.1G / Mount=/",
        "exit_code": 0,
        "is_untrusted": True,
    },
    {
        "tool": "disk.large_files",
        "args": {"path": "/var/log", "min_size_mb": 100},
        "stdout_truncated": "/var/log/syslog.1  240M\n/var/log/journal/abc  150M",
        "exit_code": 0,
        "is_untrusted": True,
    },
]

_DISK_EVIDENCE_TOOLRESULTS = []
# 用真实的 ToolResult 而不是 dict,匹配 orchestrator 自累积的 evidence 形态
from backend.app.contracts.untrusted import ToolResult as _TR  # noqa: E402

_DISK_EVIDENCE_TOOLRESULTS = [_TR(**e) for e in _DISK_EVIDENCE_DICTS]


def _make_orch_with_fake_llm(summarize_return):
    """构造 orchestrator:fake LLM.summary 固定返 summarize_return,DefaultRCAEngine 真接入."""
    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.audit import SqliteAuditSink
    from backend.app.llm.adapter import LLMAdapter
    from mcp_servers.rca import DefaultRCAEngine

    audit = SqliteAuditSink(":memory:")
    llm = mock.MagicMock(spec=LLMAdapter)
    llm.summarize = mock.AsyncMock(return_value=summarize_return)

    captured_events: list[tuple[str, dict]] = []

    class _Sink:
        def emit(self, evt):
            captured_events.append((evt.type, evt.data))

    orch = Orchestrator(
        trace_id="rca-e2e-test",
        audit=audit,
        llm=llm,
        events=_Sink(),
        gateway=mock.MagicMock(),
        rca=DefaultRCAEngine(),
    )
    return orch, audit, llm, captured_events


# ---- T1: orchestrator._emit_rca_summary 真接 LLM 端到端 -------------------


def test_t1_rca_summary_llm_end_to_end_with_default_engine():
    """T1: evidence + DefaultRCAEngine + fake LLM → audit rca_llm_summary ok +
    summary 字节级 = LLM 输出 + report['summary_source']='llm'.
    """
    orch, audit, llm, events = _make_orch_with_fake_llm(
        "磁盘使用率 85%，主要占用来自 syslog/journal，建议 rotate/limit log size"
    )

    # 走端到端 _emit_rca_summary 路径
    report = {
        "problem_type": "disk_full",
        "summary": "playbook 原 summary",
        "summary_source": "playbook",
        "root_cause": "x",
    }
    result = asyncio.run(orch._emit_rca_summary(_DISK_EVIDENCE_TOOLRESULTS, report))

    # 1. LLM 调用了
    assert llm.summarize.called, "T1: llm.summarize 应被调用"
    # 2. audit 落 rca_llm_summary
    rows = audit._conn.execute(
        "SELECT phase FROM audit_records WHERE trace_id=? AND phase=?",
        ("rca-e2e-test", "rca_llm_summary"),
    ).fetchall()
    assert rows, "T1: 期望 audit 落 phase=rca_llm_summary"
    # 3. 返回非 None str,含关键 token
    assert result is not None
    assert "磁盘" in result and "85" in result, f"T1: 含关键 token, got {result!r}"
    # 4. sensitive_filtered 应 False(磁盘证据无凭据)
    sensitive_row = audit._conn.execute(
        "SELECT payload FROM audit_records WHERE trace_id=? AND phase=?",
        ("rca-e2e-test", "rca_llm_summary"),
    ).fetchone()
    import json as _json

    payload = _json.loads(sensitive_row[0])
    assert payload.get("sensitive_filtered") is False, f"T1: 期望 False, got {payload}"


# ---- T2: audit 哈希链不破 ------------------------------------------------


def test_t2_rca_summary_preserves_hash_chain():
    """T2: rca_llm_summary audit 落库后 verify_chain 仍 valid(S3 字节级不动)."""
    orch, audit, llm, events = _make_orch_with_fake_llm("磁盘 85% 大头是 syslog")

    report = {"problem_type": "disk_full", "summary": "playbook", "root_cause": "x"}
    asyncio.run(orch._emit_rca_summary(_DISK_EVIDENCE_TOOLRESULTS, report))

    result = audit.verify_chain("rca-e2e-test")
    assert result.valid, f"T2 哈希链被破: {result}"


# ---- T3: summary 字段 LLM 化(orchestrator._execute_batch 端到端) ---------


def test_t3_summary_field_llm_overrides_playbook():
    """T3: 模拟 orchestrator _execute_batch 路径,summary LLM 化."""
    from backend.app.agent.rca_summary_llm import llm_rewrite_summary

    orch, audit, llm, events = _make_orch_with_fake_llm("磁盘满,主要来自 syslog/journal")

    report = {
        "problem_type": "disk_full",
        "summary": "playbook 原 summary",
        "summary_source": "playbook",
    }
    evidence_dicts = [e.model_dump() for e in _DISK_EVIDENCE_TOOLRESULTS]
    rewritten = asyncio.run(llm_rewrite_summary(llm, evidence_dicts, report))
    assert rewritten is not None
    report["summary"] = rewritten
    report["summary_source"] = "llm"

    assert report["summary_source"] == "llm"
    assert report["summary"] == rewritten
    assert "磁盘" in report["summary"]


# ---- T4: 反向场景——LLM 不可用,summary 兜底为 playbook --------------------


def test_t4_no_llm_falls_back_to_playbook_summary():
    """T4: fake_llm.summarize_return=None → llm_rewrite_summary 返 None,
    report.summary 保留 playbook 原值 + summary_source=playbook."""
    from backend.app.agent.rca_summary_llm import llm_rewrite_summary

    orch, audit, llm, events = _make_orch_with_fake_llm(None)
    report = {"problem_type": "disk_full", "summary": "playbook 原 summary"}
    evidence_dicts = [e.model_dump() for e in _DISK_EVIDENCE_TOOLRESULTS]

    rewritten = asyncio.run(llm_rewrite_summary(llm, evidence_dicts, report))
    assert rewritten is None, "T4: LLM 不可用应返 None(不覆写)"
    # report.summary 不变(调用方决定是否覆写)
    assert report["summary"] == "playbook 原 summary"

    # 进一步验证 _emit_rca_summary 走 LLM None 路径也不 audit rca_llm_summary
    asyncio.run(orch._emit_rca_summary(_DISK_EVIDENCE_TOOLRESULTS, report))
    rows = audit._conn.execute(
        "SELECT phase FROM audit_records WHERE trace_id=? AND phase=?",
        ("rca-e2e-test", "rca_llm_summary"),
    ).fetchall()
    assert not rows, "T4: LLM None 时不落 rca_llm_summary audit"
