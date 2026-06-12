"""SqliteAuditSink（D）：哈希链审计落库 + verify_chain 链校验。

铁律：
- S7：append 不重算 hash——orchestrator 已用 compute_curr_hash 构造好 AuditRecord，
  这里只原样 INSERT；payload 用 contracts.audit.canonical_json 序列化入库，
  verify 复算一律走 compute_curr_hash，绝不另写序列化。
- F3：verify_chain 返回 ChainVerifyResult，字段用 valid（bool），不用 ok。
- 确定性：verify 纯读 + 纯复算，无随机/无时间依赖（created_at 只入库不参与 hash）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend.app.audit.report import ChainVerifyResult
from backend.app.contracts.audit import (
    GENESIS_HASH,
    AuditRecord,
    canonical_json,
    compute_curr_hash,
)
from backend.app.db.session import connect


class SqliteAuditSink:
    """agent.ports.AuditSink 的 SQLite 实现（结构化 duck-typing 满足 Protocol）。

    生命周期：L 在 api 层把 get_audit() 升为 lifespan 单例（持 DB 句柄）；
    本类支持单例化——跨线程共享一个连接，写入用锁串行。
    """

    def __init__(self, db: str | Path | sqlite3.Connection = ":memory:") -> None:
        self._conn = db if isinstance(db, sqlite3.Connection) else connect(db)
        self._lock = threading.Lock()

    def append(self, record: AuditRecord) -> None:
        """同步落库一条审计记录。S7：只落库，绝不重算/覆盖 hash。

        (trace_id, seq) UNIQUE 兜底重复写入：同链同序重复 append 属自身 bug，
        让 sqlite3.IntegrityError 直接抛出（系统级故障语义）。
        """
        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_records "
                "(trace_id, seq, phase, payload, prev_hash, curr_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.trace_id,
                    record.seq,
                    record.phase,
                    canonical_json(record.payload),
                    record.prev_hash,
                    record.curr_hash,
                    created_at,
                ),
            )
            self._conn.commit()

    def verify_chain(self, trace_id: str) -> ChainVerifyResult:
        """按 seq 升序取整链复算比对。

        校验：seq 自 0 连续递增；首条 prev_hash == GENESIS_HASH；
        第 i 条 prev_hash == 第 i-1 条 curr_hash；逐条 compute_curr_hash 复算比对。
        任一不符 → valid=False + 第一个出错 seq + 原因。
        """
        rows = self._conn.execute(
            "SELECT seq, payload, prev_hash, curr_hash "
            "FROM audit_records WHERE trace_id = ? ORDER BY seq ASC",
            (trace_id,),
        ).fetchall()
        expected_prev = GENESIS_HASH
        for index, row in enumerate(rows):
            seq = row["seq"]
            if seq != index:
                reason = f"缺号/跳号：期望 seq={index}，实际 seq={seq}"
                return self._broken(trace_id, len(rows), seq, reason)
            if row["prev_hash"] != expected_prev:
                reason = (
                    "首条 prev_hash 不等于 GENESIS_HASH"
                    if index == 0
                    else "断链/重排：prev_hash 与前一条 curr_hash 不一致"
                )
                return self._broken(trace_id, len(rows), seq, reason)
            recomputed = compute_curr_hash(row["prev_hash"], json.loads(row["payload"]))
            if recomputed != row["curr_hash"]:
                reason = "篡改：curr_hash 复算不一致（payload 或 hash 被改）"
                return self._broken(trace_id, len(rows), seq, reason)
            expected_prev = row["curr_hash"]
        return ChainVerifyResult(
            valid=True, trace_id=trace_id, record_count=len(rows), broken_seq=None, reason=""
        )

    def last_hash(self, trace_id: str) -> str:
        """返回该 trace 最大 seq 的 curr_hash；无记录返回 GENESIS_HASH（供 L resume 取 prev）。"""
        row = self._conn.execute(
            "SELECT curr_hash FROM audit_records WHERE trace_id = ? ORDER BY seq DESC LIMIT 1",
            (trace_id,),
        ).fetchone()
        return row["curr_hash"] if row is not None else GENESIS_HASH

    def close(self) -> None:
        """关闭底层连接（lifespan shutdown 时由 L 调用）。"""
        self._conn.close()

    @staticmethod
    def _broken(trace_id: str, count: int, seq: int, reason: str) -> ChainVerifyResult:
        return ChainVerifyResult(
            valid=False, trace_id=trace_id, record_count=count, broken_seq=seq, reason=reason
        )
