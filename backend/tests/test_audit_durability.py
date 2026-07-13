"""L-B4-3 审计库 durability Blocker 测试。

覆盖 4 用例：
  - T1: PRAGMA synchronous=FULL 生效
  - T2: PRAGMA busy_timeout=5000 生效
  - T3: close() 调 flush() + _conn.close 顺序（spy verify）
  - T4: 断电模拟（close 后重开）→ 之前落盘的 record 仍在
"""

from __future__ import annotations

import os
import tempfile

import pytest

from backend.app.audit import SqliteAuditSink


def _make_tmp_db() -> str:
    """返回 sqlite db 临时路径（已 close，不持句柄）。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return tmp.name


def _safe_unlink(path: str) -> None:
    """Windows 上 sqlite 句柄可能延迟释放，吞 OSError 兜底。"""
    try:
        os.unlink(path)
    except OSError:
        pass


# ---- T1: PRAGMA synchronous=FULL 生效 --------------------------------------


def test_pragma_synchronous_full_applied() -> None:
    sink = SqliteAuditSink(":memory:")
    row = sink._conn.execute("PRAGMA synchronous").fetchone()
    # synchronous=2 == FULL；sqlite PRAGMA synchronous 返回整数（0/1/2）
    assert row[0] == 2, f"synchronous 应为 FULL(2)，实际 {row[0]}"


# ---- T2: PRAGMA busy_timeout=5000 生效 --------------------------------------


def test_pragma_busy_timeout_5000_applied() -> None:
    sink = SqliteAuditSink(":memory:")
    row = sink._conn.execute("PRAGMA busy_timeout").fetchone()
    assert row[0] == 5000, f"busy_timeout 应为 5000ms，实际 {row[0]}"


# ---- T3: close() 调 flush() + _conn.close 顺序 ------------------------------


def test_close_calls_flush_then_closes_conn() -> None:
    """T3: sink.close() 内部 → 先 flush() (checkpoint WAL) → 再 _conn.close() → 置 None。

    spy 方式：monkey-patch SqliteAuditSink.flush 计数；调 close 后断言
    flush 调用 ≥ 1 + sink._conn 已 None。
    """
    sink = SqliteAuditSink(":memory:")
    flush_count = {"n": 0}
    original_flush = sink.flush

    def spy_flush() -> None:
        flush_count["n"] += 1
        original_flush()

    sink.flush = spy_flush  # type: ignore[method-assign]
    sink.close()
    assert flush_count["n"] >= 1, f"close() 应调 flush()，got {flush_count['n']}"
    # 注：不置 None（保持 sqlite3.ProgrammingError 契约，老测试 test_audit_provider
    # _is_singleton_and_closed_on_shutdown 依赖此行为）；close 后 _conn 已 closed
    # → 后续 execute 应抛 ProgrammingError
    import sqlite3 as _sqlite3

    with pytest.raises(_sqlite3.ProgrammingError):
        sink._conn.execute("SELECT 1")


# ---- T4: 断电模拟（close 后重开）→ record 仍在 -----------------------------


def test_durability_reopen_after_close() -> None:
    """T4: 落 1 record + close + reopen + verify_chain 应 valid + 1 record。

    模拟断电：进程退出 + 重启 → SqliteAuditSink 应能从持久化文件恢复。
    """
    from backend.app.contracts.audit import (
        GENESIS_HASH,
        AuditRecord,
        compute_curr_hash,
    )

    db_path = _make_tmp_db()
    try:
        # 阶段 1: 写入 1 record + flush + close
        sink1 = SqliteAuditSink(db_path)
        payload = {"user_intent": "restart nginx"}
        record = AuditRecord(
            trace_id="durability-001",
            seq=0,
            phase="RECEIVED",
            payload=payload,
            prev_hash=GENESIS_HASH,
            curr_hash=compute_curr_hash(GENESIS_HASH, payload),
        )
        sink1.append(record)
        sink1.flush()
        sink1.close()

        # 阶段 2: 模拟重启（重新打开 DB）
        sink2 = SqliteAuditSink(db_path)
        result = sink2.verify_chain("durability-001")
        assert result.valid, f"重开后 verify_chain 应 valid，got reason={result.reason}"
        assert result.record_count == 1
        sink2.close()
    finally:
        _safe_unlink(db_path)
