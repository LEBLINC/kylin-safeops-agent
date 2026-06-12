"""SqliteAuditSink（SQLite 落库 + 哈希链校验）测试 — PR3。

要点：
- S7：append 只落库不重算 hash（错 hash 原样入库，由 verify_chain 检出）；
- F3：verify_chain 返回 ChainVerifyResult，字段用 valid；
- E3/E4：落库后真篡改（UPDATE payload）/ 重排断链 → invalid + 第一个出错 seq；
- 边界：空 trace / 单条 / seq 跳号 / UNIQUE 冲突 / GENESIS 不符；
- 性能：单条 append < 100ms；结构一致性：满足 AuditSink Protocol。
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from backend.app.agent.ports import AuditSink
from backend.app.audit import ChainVerifyResult, SqliteAuditSink
from backend.app.contracts.audit import (
    GENESIS_HASH,
    AuditRecord,
    canonical_json,
    compute_curr_hash,
)


def _chain(trace_id: str, payloads: list[dict]) -> list[AuditRecord]:
    """按契约哈希链规则构造一条合法链（orchestrator 侧职责的测试替身）。"""
    records: list[AuditRecord] = []
    prev = GENESIS_HASH
    for seq, payload in enumerate(payloads):
        curr = compute_curr_hash(prev, payload)
        records.append(
            AuditRecord(
                trace_id=trace_id,
                seq=seq,
                phase=f"phase_{seq}",
                payload=payload,
                prev_hash=prev,
                curr_hash=curr,
            )
        )
        prev = curr
    return records


_PAYLOADS = [
    {"user_intent": "查看磁盘占用", "risk_level": "R0"},
    {"tool_plan": ["disk.usage"], "approval_required": False},
    {"tool": "disk.usage", "exit_code": 0, "executed": True},
    {"verify_result": "ok", "observations": ["磁盘占用 42%"]},
]


@pytest.fixture()
def sink() -> SqliteAuditSink:
    return SqliteAuditSink(":memory:")


def _fill(sink: SqliteAuditSink, trace_id: str, payloads: list[dict]) -> list[AuditRecord]:
    records = _chain(trace_id, payloads)
    for record in records:
        sink.append(record)
    return records


# ---- 正常链 -----------------------------------------------------------------


def test_append_then_verify_valid(sink: SqliteAuditSink) -> None:
    _fill(sink, "t-1", _PAYLOADS)
    result = sink.verify_chain("t-1")
    assert isinstance(result, ChainVerifyResult)
    assert result.valid is True
    assert result.record_count == 4
    assert result.broken_seq is None and result.reason == ""
    assert "ok" not in ChainVerifyResult.model_fields  # F3：字段口径是 valid


def test_single_record_chain_valid(sink: SqliteAuditSink) -> None:
    _fill(sink, "t-one", _PAYLOADS[:1])
    assert sink.verify_chain("t-one").valid is True


def test_empty_trace_valid(sink: SqliteAuditSink) -> None:
    result = sink.verify_chain("no-such-trace")
    assert result.valid is True and result.record_count == 0


def test_non_ascii_payload_roundtrip(sink: SqliteAuditSink) -> None:
    _fill(sink, "t-cjk", [{"intent": "清理 /var/log 日志", "嵌套": {"列表": [1, "二", None]}}])
    assert sink.verify_chain("t-cjk").valid is True


# ---- S7：append 只落库不重算 ------------------------------------------------


def test_append_does_not_recompute_hash(sink: SqliteAuditSink) -> None:
    """错误 curr_hash 原样入库（证明 append 没重算覆盖），verify_chain 随后检出。"""
    wrong = "f" * 64
    sink.append(
        AuditRecord(
            trace_id="t-bad",
            seq=0,
            phase="plan",
            payload={"k": "v"},
            prev_hash=GENESIS_HASH,
            curr_hash=wrong,
        )
    )
    row = sink._conn.execute(
        "SELECT curr_hash, payload FROM audit_records WHERE trace_id = 't-bad'"
    ).fetchone()
    assert row["curr_hash"] == wrong
    assert row["payload"] == canonical_json({"k": "v"})
    result = sink.verify_chain("t-bad")
    assert result.valid is False and result.broken_seq == 0
    assert "篡改" in result.reason


# ---- E3/E4：真篡改 / 重排 / 断链 --------------------------------------------


def test_tamper_middle_payload_detected(sink: SqliteAuditSink) -> None:
    _fill(sink, "t-2", _PAYLOADS)
    sink._conn.execute(
        "UPDATE audit_records SET payload = ? WHERE trace_id = 't-2' AND seq = 1",
        (canonical_json({"tool_plan": ["service.restart"], "approval_required": False}),),
    )
    result = sink.verify_chain("t-2")
    assert result.valid is False and result.broken_seq == 1


def test_reorder_records_detected(sink: SqliteAuditSink) -> None:
    """交换两条记录的 seq（重排）→ prev_hash 链接对不上。"""
    _fill(sink, "t-3", _PAYLOADS)
    sink._conn.executescript(
        "UPDATE audit_records SET seq = 99 WHERE trace_id = 't-3' AND seq = 1;"
        "UPDATE audit_records SET seq = 1 WHERE trace_id = 't-3' AND seq = 2;"
        "UPDATE audit_records SET seq = 2 WHERE trace_id = 't-3' AND seq = 99;"
    )
    result = sink.verify_chain("t-3")
    assert result.valid is False and result.broken_seq == 1


def test_broken_prev_hash_link_detected(sink: SqliteAuditSink) -> None:
    _fill(sink, "t-4", _PAYLOADS)
    sink._conn.execute(
        "UPDATE audit_records SET prev_hash = ? WHERE trace_id = 't-4' AND seq = 2",
        ("9" * 64,),
    )
    result = sink.verify_chain("t-4")
    assert result.valid is False and result.broken_seq == 2
    assert "断链" in result.reason or "重排" in result.reason


def test_delete_middle_record_detected(sink: SqliteAuditSink) -> None:
    _fill(sink, "t-5", _PAYLOADS)
    sink._conn.execute("DELETE FROM audit_records WHERE trace_id = 't-5' AND seq = 1")
    result = sink.verify_chain("t-5")
    assert result.valid is False and result.broken_seq == 2  # seq 跳变处即第一个出错点


# ---- 边界：GENESIS / 跳号 / UNIQUE ------------------------------------------


def test_first_record_prev_not_genesis_detected(sink: SqliteAuditSink) -> None:
    payload = {"k": "v"}
    prev = "a" * 64
    sink.append(
        AuditRecord(
            trace_id="t-6",
            seq=0,
            phase="plan",
            payload=payload,
            prev_hash=prev,
            curr_hash=compute_curr_hash(prev, payload),
        )
    )
    result = sink.verify_chain("t-6")
    assert result.valid is False and result.broken_seq == 0
    assert "GENESIS" in result.reason


def test_seq_gap_detected(sink: SqliteAuditSink) -> None:
    records = _chain("t-7", _PAYLOADS[:3])
    sink.append(records[0])
    sink.append(records[2].model_copy(update={"seq": 2}))  # 跳过 seq=1
    result = sink.verify_chain("t-7")
    assert result.valid is False and result.broken_seq == 2
    assert "缺号" in result.reason or "跳号" in result.reason


def test_duplicate_trace_seq_raises(sink: SqliteAuditSink) -> None:
    """同链同 seq 重复 append = 自身 bug → UNIQUE 冲突直接抛（系统级故障语义）。"""
    record = _chain("t-dup", [{"a": 1}])[0]
    sink.append(record)
    with pytest.raises(sqlite3.IntegrityError):
        sink.append(record)


def test_traces_are_isolated(sink: SqliteAuditSink) -> None:
    _fill(sink, "t-a", _PAYLOADS[:2])
    _fill(sink, "t-b", _PAYLOADS)
    assert sink.verify_chain("t-a").record_count == 2
    assert sink.verify_chain("t-b").record_count == 4


# ---- last_hash 辅助 ----------------------------------------------------------


def test_last_hash(sink: SqliteAuditSink) -> None:
    assert sink.last_hash("t-new") == GENESIS_HASH
    records = _fill(sink, "t-8", _PAYLOADS)
    assert sink.last_hash("t-8") == records[-1].curr_hash


# ---- 性能 + Protocol 结构一致性 ----------------------------------------------


def test_append_under_100ms(tmp_path) -> None:
    sink = SqliteAuditSink(tmp_path / "audit.db")  # 真落盘粗测
    record = _chain("t-perf", [{"k": "v"}])[0]
    start = time.perf_counter()
    sink.append(record)
    assert (time.perf_counter() - start) < 0.1
    sink.close()


def test_satisfies_audit_sink_protocol(sink: SqliteAuditSink) -> None:
    assert isinstance(sink, AuditSink)
