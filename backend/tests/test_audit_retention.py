"""审计库 retention/rotation 测试（Phase 3b，决策⑪）。

覆盖：终态闸（FINISHED/REJECTED 可归档；WAIT_APPROVAL/EXECUTING 不归档）、时间缓冲、
不破链、先验后删、rotation+VACUUM、空操作、CLI 拒 :memory:、确定性。

造数据：用 SqliteAuditSink.append 构造带 GENESIS 链的多 trace（复用 compute_curr_hash
造合法链），再 UPDATE created_at 钉死时间（created_at 不入 hash，不破链）。
Linux/Win 通用（纯 sqlite，不依赖 chmod；权限位测试归 3a）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.audit import SqliteAuditSink
from backend.app.audit.maintenance import (
    RetentionReport,
    _before_iso,
    main,
    run_retention,
)
from backend.app.contracts.audit import GENESIS_HASH, AuditRecord, compute_curr_hash

# 钉死的“现在”（注入 run_retention，保证确定性）。
NOW_ISO = "2026-06-16T00:00:00+00:00"
OLD_ISO = "2020-01-01T00:00:00+00:00"  # 远早于 NOW-90d → 过时间缓冲
RECENT_ISO = "2026-06-15T00:00:00+00:00"  # NOW-1d → 在缓冲窗口内


def _append_chain(
    sink: SqliteAuditSink,
    trace_id: str,
    phases: list[str],
    *,
    created_at: str | None = None,
) -> None:
    """按 GENESIS 链规则 append 一条 trace；可选钉死 created_at。"""
    prev = GENESIS_HASH
    for seq, phase in enumerate(phases):
        payload = {"phase": phase, "seq": seq}
        curr = compute_curr_hash(prev, payload)
        sink.append(
            AuditRecord(
                trace_id=trace_id,
                seq=seq,
                phase=phase,
                payload=payload,
                prev_hash=prev,
                curr_hash=curr,
            )
        )
        prev = curr
    if created_at is not None:
        sink._conn.execute(
            "UPDATE audit_records SET created_at = ? WHERE trace_id = ?",
            (created_at, trace_id),
        )
        sink._conn.commit()


_CLOSED = ["RECEIVED", "POLICY_CHECKED", "EXECUTING", "EXECUTED", "VERIFIED", "FINISHED"]
_REJECTED = ["RECEIVED", "POLICY_CHECKED", "REJECTED"]
_WAIT = ["RECEIVED", "POLICY_CHECKED", "WAIT_APPROVAL"]
_INFLIGHT = ["RECEIVED", "POLICY_CHECKED", "EXECUTING"]


# ---- 终态闸（iter_closed_traces，内存库直测）--------------------------------

BEFORE_ISO = _before_iso(NOW_ISO, 90)


def test_gate_finished_trace_eligible() -> None:
    sink = SqliteAuditSink(":memory:")
    _append_chain(sink, "t-fin", _CLOSED, created_at=OLD_ISO)
    assert sink.iter_closed_traces(before_iso=BEFORE_ISO) == ["t-fin"]


def test_gate_rejected_trace_eligible() -> None:
    sink = SqliteAuditSink(":memory:")
    _append_chain(sink, "t-rej", _REJECTED, created_at=OLD_ISO)
    assert sink.iter_closed_traces(before_iso=BEFORE_ISO) == ["t-rej"]


def test_gate_wait_approval_excluded() -> None:
    sink = SqliteAuditSink(":memory:")
    _append_chain(sink, "t-wait", _WAIT, created_at=OLD_ISO)  # 即使很旧
    assert sink.iter_closed_traces(before_iso=BEFORE_ISO) == []
    assert sink.count_in_flight_traces() == 1


def test_gate_in_flight_executing_excluded() -> None:
    sink = SqliteAuditSink(":memory:")
    _append_chain(sink, "t-exec", _INFLIGHT, created_at=OLD_ISO)
    assert sink.iter_closed_traces(before_iso=BEFORE_ISO) == []
    assert sink.count_in_flight_traces() == 1


def test_time_buffer_recent_not_eligible() -> None:
    sink = SqliteAuditSink(":memory:")
    _append_chain(sink, "t-new", _CLOSED, created_at=RECENT_ISO)  # 终态但太新
    assert sink.iter_closed_traces(before_iso=BEFORE_ISO) == []
    assert sink.count_in_flight_traces() == 0  # 已达终态，不算 in-flight


def test_gate_ordering_deterministic() -> None:
    sink = SqliteAuditSink(":memory:")
    _append_chain(sink, "t-b", _CLOSED, created_at=OLD_ISO)
    _append_chain(sink, "t-a", _REJECTED, created_at=OLD_ISO)
    assert sink.iter_closed_traces(before_iso=BEFORE_ISO) == ["t-a", "t-b"]


# ---- run_retention 集成（文件库）------------------------------------------


def _build_db(path: Path, specs: list[tuple[str, list[str], str]]) -> None:
    """在 path 建库并按 specs=[(trace_id, phases, created_at)] 造数据后关闭。"""
    sink = SqliteAuditSink(str(path))
    for trace_id, phases, created_at in specs:
        _append_chain(sink, trace_id, phases, created_at=created_at)
    sink.close()


def test_finished_archived_and_chain_intact(tmp_path: Path) -> None:
    db = tmp_path / "audit.db"
    _build_db(
        db,
        [
            ("t-old", _CLOSED, OLD_ISO),  # 应归档
            ("t-keep", _CLOSED, RECENT_ISO),  # 太新，保留
        ],
    )
    report = run_retention(
        str(db), retention_days=90, max_bytes=_big(), archive_dir=None, now_iso=NOW_ISO
    )
    assert report.archived_traces == ["t-old"]
    assert report.archived_records == len(_CLOSED)
    assert report.archive_db_path is not None

    # 先验后删：主库无 t-old、保留 t-keep 且仍 valid；归档库有 t-old 且 valid。
    main_sink = SqliteAuditSink(str(db))
    assert main_sink.verify_chain("t-old").record_count == 0
    assert main_sink.verify_chain("t-keep").valid is True
    assert main_sink.verify_chain("t-keep").record_count == len(_CLOSED)
    main_sink.close()

    arch_sink = SqliteAuditSink(report.archive_db_path)
    res = arch_sink.verify_chain("t-old")
    assert res.valid is True and res.record_count == len(_CLOSED)
    arch_sink.close()


def test_archive_db_name_uses_now_month(tmp_path: Path) -> None:
    db = tmp_path / "audit.db"
    _build_db(db, [("t-old", _CLOSED, OLD_ISO)])
    report = run_retention(
        str(db), retention_days=90, max_bytes=_big(), archive_dir=None, now_iso=NOW_ISO
    )
    assert report.archive_db_path is not None
    assert Path(report.archive_db_path).name == "audit.archive.202606.db"
    assert Path(report.archive_db_path).parent == db.resolve().parent


def test_archive_dir_override(tmp_path: Path) -> None:
    db = tmp_path / "main" / "audit.db"
    db.parent.mkdir(parents=True)
    _build_db(db, [("t-old", _CLOSED, OLD_ISO)])
    arch_dir = tmp_path / "archive"
    report = run_retention(
        str(db),
        retention_days=90,
        max_bytes=_big(),
        archive_dir=str(arch_dir),
        now_iso=NOW_ISO,
    )
    assert report.archive_db_path is not None
    assert Path(report.archive_db_path).parent == arch_dir


def test_rotation_vacuum_shrinks(tmp_path: Path) -> None:
    db = tmp_path / "audit.db"
    # 多条大 payload 的旧终态 trace，制造可观体积。
    sink = SqliteAuditSink(str(db))
    big = "x" * 4096
    for i in range(20):
        prev = GENESIS_HASH
        tid = f"t-{i:02d}"
        for seq, phase in enumerate(["RECEIVED", "EXECUTED", "FINISHED"]):
            payload = {"phase": phase, "blob": big, "seq": seq}
            curr = compute_curr_hash(prev, payload)
            sink.append(
                AuditRecord(
                    trace_id=tid,
                    seq=seq,
                    phase=phase,
                    payload=payload,
                    prev_hash=prev,
                    curr_hash=curr,
                )
            )
            prev = curr
        sink._conn.execute(
            "UPDATE audit_records SET created_at = ? WHERE trace_id = ?", (OLD_ISO, tid)
        )
    sink._conn.commit()
    before = sink.db_size_bytes()
    sink.close()

    # max_bytes 设极小 → rotation 阈值触发；候选齐全 → 归档 + VACUUM。
    report = run_retention(
        str(db), retention_days=90, max_bytes=1, archive_dir=None, now_iso=NOW_ISO
    )
    assert len(report.archived_traces) == 20
    assert report.main_db_bytes_after < before
    assert report.freed_bytes > 0


def test_noop_when_nothing_due(tmp_path: Path) -> None:
    db = tmp_path / "audit.db"
    _build_db(db, [("t-keep", _CLOSED, RECENT_ISO)])  # 终态但太新
    main_sink = SqliteAuditSink(str(db))
    count_before = main_sink.verify_chain("t-keep").record_count
    main_sink.close()

    report = run_retention(
        str(db), retention_days=90, max_bytes=_big(), archive_dir=None, now_iso=NOW_ISO
    )
    assert report == RetentionReport(
        archived_traces=[],
        archived_records=0,
        freed_bytes=0,
        main_db_bytes_after=report.main_db_bytes_after,
        skipped_in_flight=0,
        archive_db_path=None,
    )
    main_sink = SqliteAuditSink(str(db))
    assert main_sink.verify_chain("t-keep").record_count == count_before
    main_sink.close()


def test_verify_failure_is_conservative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """归档库 verify 不通过时，保守不删主库（先验后删铁律）。"""
    db = tmp_path / "audit.db"
    _build_db(db, [("t-old", _CLOSED, OLD_ISO)])

    from backend.app.audit import audit_logger as mod
    from backend.app.audit.report import ChainVerifyResult

    def _always_invalid(self: SqliteAuditSink, trace_id: str) -> ChainVerifyResult:
        return ChainVerifyResult(
            valid=False, trace_id=trace_id, record_count=0, broken_seq=0, reason="forced"
        )

    monkeypatch.setattr(mod.SqliteAuditSink, "verify_chain", _always_invalid)
    report = run_retention(
        str(db), retention_days=90, max_bytes=1, archive_dir=None, now_iso=NOW_ISO
    )
    assert report.archived_traces == []
    assert report.archived_records == 0
    # 主库仍保有 t-old（未删）。
    main_sink = SqliteAuditSink(str(db))
    rows = main_sink._conn.execute(
        "SELECT COUNT(*) AS n FROM audit_records WHERE trace_id = 't-old'"
    ).fetchone()
    assert rows["n"] == len(_CLOSED)
    main_sink.close()


def test_verify_failure_rerun_no_unique_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """verify 持续失败时，二次 run 不因归档库 UNIQUE 冲突崩溃（export_trace OR IGNORE 幂等）。

    场景：一条坏 trace 第一轮 export 已写入归档库但 verify 失败(保守不删主库)；
    第二轮该 trace 仍是候选，再次 export 同 (trace_id, seq)——若用普通 INSERT 会撞
    UNIQUE 抛 IntegrityError，一条坏 trace 阻塞所有后续 retention。OR IGNORE 须使其幂等。
    """
    db = tmp_path / "audit.db"
    _build_db(db, [("t-bad", _CLOSED, OLD_ISO)])

    from backend.app.audit import audit_logger as mod
    from backend.app.audit.report import ChainVerifyResult

    def _always_invalid(self: SqliteAuditSink, trace_id: str) -> ChainVerifyResult:
        return ChainVerifyResult(
            valid=False, trace_id=trace_id, record_count=0, broken_seq=0, reason="forced"
        )

    monkeypatch.setattr(mod.SqliteAuditSink, "verify_chain", _always_invalid)
    # 两轮均不应抛（第二轮命中归档库已存在行，OR IGNORE 跳过）。
    for _ in range(2):
        report = run_retention(
            str(db), retention_days=90, max_bytes=1, archive_dir=None, now_iso=NOW_ISO
        )
        assert report.archived_traces == []
    # 主库仍完整保有坏 trace（始终未删）。
    main_sink = SqliteAuditSink(str(db))
    n = main_sink._conn.execute(
        "SELECT COUNT(*) AS n FROM audit_records WHERE trace_id = 't-bad'"
    ).fetchone()["n"]
    main_sink.close()
    assert n == len(_CLOSED)


def test_determinism_same_now_same_result(tmp_path: Path) -> None:
    specs = [("t-old", _CLOSED, OLD_ISO), ("t-keep", _CLOSED, RECENT_ISO)]
    # 两次跑用独立目录（各自归档库），仅对比 report 内容以验证确定性。
    d1, d2 = tmp_path / "run1", tmp_path / "run2"
    d1.mkdir()
    d2.mkdir()
    db1, db2 = d1 / "audit.db", d2 / "audit.db"
    _build_db(db1, specs)
    _build_db(db2, specs)
    r1 = run_retention(
        str(db1), retention_days=90, max_bytes=_big(), archive_dir=None, now_iso=NOW_ISO
    )
    r2 = run_retention(
        str(db2), retention_days=90, max_bytes=_big(), archive_dir=None, now_iso=NOW_ISO
    )
    assert r1.archived_traces == r2.archived_traces == ["t-old"]
    assert r1.archived_records == r2.archived_records
    assert r1.skipped_in_flight == r2.skipped_in_flight == 0


# ---- 小单元 ----------------------------------------------------------------


def test_db_size_memory_is_zero() -> None:
    assert SqliteAuditSink(":memory:").db_size_bytes() == 0


def test_export_delete_roundtrip(tmp_path: Path) -> None:
    src = SqliteAuditSink(str(tmp_path / "src.db"))
    dst = SqliteAuditSink(str(tmp_path / "dst.db"))
    _append_chain(src, "t-x", _CLOSED, created_at=OLD_ISO)
    n = src.export_trace("t-x", dst._conn)
    assert n == len(_CLOSED)
    assert dst.verify_chain("t-x").valid is True
    assert src.delete_trace("t-x") == len(_CLOSED)
    assert src.verify_chain("t-x").record_count == 0
    src.close()
    dst.close()


# ---- CLI ------------------------------------------------------------------


def test_cli_rejects_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KYLIN_AUDIT_DB", ":memory:")
    assert main([]) == 1


def test_cli_rejects_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KYLIN_AUDIT_DB", raising=False)
    assert main([]) == 1


def test_cli_runs_and_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "audit.db"
    _build_db(db, [("t-old", _CLOSED, OLD_ISO)])
    monkeypatch.setenv("KYLIN_AUDIT_DB", str(db))
    monkeypatch.setenv("KYLIN_AUDIT_RETENTION_DAYS", "90")
    monkeypatch.delenv("KYLIN_AUDIT_MAX_BYTES", raising=False)
    monkeypatch.delenv("KYLIN_AUDIT_ARCHIVE_DIR", raising=False)
    assert main([]) == 0


def _big() -> int:
    """足够大的 max_bytes，使 rotation 阈值不触发（仅测 retention 路径）。"""
    return 10 * 1024 * 1024 * 1024
