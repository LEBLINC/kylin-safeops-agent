"""RCA P4 真接 + C1 summarize metrics 守门测试。

覆盖 4 用例：
  T1 _emit_rca_summary 成功路径：mock summarize 返非空字符串
     → rca 事件 data 含 llm_summary + audit phase=rca_llm_summary
  T2 _emit_rca_summary 返 None（LLM 拒答）→ 不 emit rca 额外事件、不 audit rca_llm_summary
  T3 C1 summarize 调用点埋点：_emit_natural_language 调用后 llm.calls 累加
  T4 C1 summarize 失败路径：_emit_natural_language 异常 → llm.failures 累加
"""

from __future__ import annotations

import asyncio
from unittest import mock

from backend.app.agent.metrics import get_metrics

# ---- 公共桩 ------------------------------------------------------------------


class _CapSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, evt) -> None:  # noqa: ANN001
        self.events.append((evt.type, evt.data))


def _build_orch(summary_retval=None):  # noqa: ANN001
    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.audit import SqliteAuditSink
    from backend.app.llm.adapter import LLMAdapter

    audit = SqliteAuditSink(":memory:")
    sink = _CapSink()
    llm = mock.MagicMock(spec=LLMAdapter)
    llm.summarize = mock.AsyncMock(return_value=summary_retval)
    gw = mock.MagicMock()
    orch = Orchestrator(
        trace_id="p4-test",
        audit=audit,
        llm=llm,
        events=sink,
        gateway=gw,
    )
    return orch, audit, sink, llm


# ---- T1: 成功路径 → rca 事件带 llm_summary + audit rca_llm_summary ----------


def test_t1_rca_summary_success_path_emits_and_audits() -> None:
    """T1: mock summarize 返 "RCA: 磁盘满" → rca 事件含 llm_summary + audit 记成功。"""
    orch, audit, sink, llm = _build_orch(summary_retval="RCA: 磁盘满，请清理日志")
    llm.summarize = mock.AsyncMock(return_value="RCA: 磁盘满，请清理日志")

    report = {"problem_type": "disk_full", "summary": "磁盘占用超 95%"}
    asyncio.run(orch._emit_rca_summary([], report))

    # 方法本身只返回 str，不直接 emit（emit 由调用方 _execute_batch 做）
    # 断言 audit 落了成功记录
    rows = audit._conn.execute(
        "SELECT phase FROM audit_records WHERE trace_id=? AND phase=?",
        ("p4-test", "rca_llm_summary"),
    ).fetchall()
    assert rows, "T1 期望 audit 落 phase=rca_llm_summary"

    # 断言返回值被接收
    retval = asyncio.run(orch._emit_rca_summary([], report))
    assert retval is not None and "磁盘满" in retval, "T1 期望返回 redacted summary 非 None"


# ---- T2: LLM 返 None → 无额外 emit + 无 rca_llm_summary audit ------------


def test_t2_rca_summary_none_return_no_emit_no_audit() -> None:
    """T2: mock summarize 返 None（拒答）→ 返回值 None + 无 rca_llm_summary audit。"""
    orch, audit, sink, llm = _build_orch(summary_retval=None)

    report = {"problem_type": "disk_full"}
    retval = asyncio.run(orch._emit_rca_summary([], report))
    assert retval is None, "T2 期望返回 None（LLM 拒答）"

    rows = audit._conn.execute(
        "SELECT phase FROM audit_records WHERE trace_id=? AND phase=?",
        ("p4-test", "rca_llm_summary"),
    ).fetchall()
    assert not rows, "T2 期望无 rca_llm_summary audit（LLM 拒答时静默）"


# ---- T3: C1 summarize 计数 → llm.calls 在 _emit_natural_language 里累加 ----


def test_t3_summarize_metrics_llm_calls_increments() -> None:
    """T3: _emit_natural_language 调用 → llm.calls counter 增加（C1 summarize 埋点）。"""
    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.audit import SqliteAuditSink
    from backend.app.contracts.untrusted import ToolResult
    from backend.app.llm.adapter import LLMAdapter

    get_metrics().reset()
    audit = SqliteAuditSink(":memory:")
    llm = mock.MagicMock(spec=LLMAdapter)
    llm.summarize = mock.AsyncMock(return_value="已完成:disk.usage")
    orch = Orchestrator(
        trace_id="c1-t3",
        audit=audit,
        llm=llm,
        events=_CapSink(),
        gateway=mock.MagicMock(),
    )
    before = get_metrics().snapshot()["counters"].get("llm.calls", 0)

    asyncio.run(
        orch._emit_natural_language(
            [ToolResult(tool="disk.usage", exit_code=0, stdout_truncated="ok")]
        )
    )
    after = get_metrics().snapshot()["counters"].get("llm.calls", 0)
    assert after == before + 1, f"T3 期望 llm.calls +1, before={before} after={after}"


# ---- T4: C1 summarize 失败计数 → llm.failures 在 _emit_natural_language 里累加


def test_t4_summarize_failure_increments_llm_failures() -> None:
    """T4: summarize 抛异常 → llm.failures counter 累加（C1 失败路径埋点）。"""
    import httpx

    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.audit import SqliteAuditSink
    from backend.app.contracts.untrusted import ToolResult
    from backend.app.llm.adapter import LLMAdapter

    get_metrics().reset()
    audit = SqliteAuditSink(":memory:")
    llm = mock.MagicMock(spec=LLMAdapter)
    llm.summarize = mock.AsyncMock(
        side_effect=httpx.TimeoutException("summarize timeout", request=None)
    )
    orch = Orchestrator(
        trace_id="c1-t4",
        audit=audit,
        llm=llm,
        events=_CapSink(),
        gateway=mock.MagicMock(),
    )
    before_f = get_metrics().snapshot()["counters"].get("llm.failures", 0)
    before_c = get_metrics().snapshot()["counters"].get("llm.calls", 0)

    asyncio.run(
        orch._emit_natural_language(
            [ToolResult(tool="disk.usage", exit_code=0, stdout_truncated="ok")]
        )
    )
    snap = get_metrics().snapshot()["counters"]
    assert snap.get("llm.failures", 0) == before_f + 1, "T4 期望 llm.failures +1"
    assert snap.get("llm.calls", 0) == before_c + 1, "T4 期望 llm.calls +1（先计再失败）"
