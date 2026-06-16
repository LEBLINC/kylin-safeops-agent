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

#: 终态相位字面值（== agent.state_machine.TERMINAL_STATES 的 .value）。
#: retention 的终态闸据此判定一条 trace 是否已闭合；此处用字面常量而非 import
#: agent 模块，保持 audit 域对编排层零运行时耦合（终态字面值已冻结，见 state_machine）。
_TERMINAL_PHASES: tuple[str, ...] = ("FINISHED", "REJECTED")
_TERMINAL_IN = ",".join("?" for _ in _TERMINAL_PHASES)


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

    # ---- retention / rotation 支撑（3b，决策⑪；带外 maintenance 调用）------------

    def iter_closed_traces(self, *, before_iso: str) -> list[str]:
        """返回【已达终态且最新记录早于 before_iso】的 trace_id 列表（终态闸 + 时间缓冲）。

        终态闸：trace 的 audit_records 含 phase IN ('FINISHED','REJECTED')。
        时间缓冲：该 trace 的 MAX(created_at) < before_iso。
        两条件 AND，一条 SQL 同时表达（不拆两趟查）。
        in-flight / WAIT_APPROVAL / 无终态的 trace 绝不入列，无论多老。
        返回按 trace_id 升序（确定性）。
        """
        rows = self._conn.execute(
            "SELECT trace_id FROM audit_records GROUP BY trace_id "
            f"HAVING SUM(CASE WHEN phase IN ({_TERMINAL_IN}) THEN 1 ELSE 0 END) > 0 "
            "AND MAX(created_at) < ? ORDER BY trace_id ASC",
            (*_TERMINAL_PHASES, before_iso),
        ).fetchall()
        return [row["trace_id"] for row in rows]

    def count_in_flight_traces(self) -> int:
        """未达终态的 trace 数（无 FINISHED/REJECTED 记录）。供 report.skipped_in_flight。"""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM ("
            "SELECT trace_id FROM audit_records GROUP BY trace_id "
            f"HAVING SUM(CASE WHEN phase IN ({_TERMINAL_IN}) THEN 1 ELSE 0 END) = 0)",
            _TERMINAL_PHASES,
        ).fetchone()
        return int(row["n"])

    def export_trace(self, trace_id: str, dest_conn: sqlite3.Connection) -> int:
        """把一条 trace 的全部 record 原样 INSERT 进 dest_conn（同 schema）。返回搬迁条数。

        原样复制 7 列（trace_id/seq/phase/payload/prev_hash/curr_hash/created_at），
        绝不重算 hash（S7）；id 为 AUTOINCREMENT，不复制。持 self._lock。
        INSERT OR IGNORE：使再次导出幂等——上一轮 verify 失败(保守不删主库)或进程中途崩
        留下的归档残留行不会触发 UNIQUE 冲突，避免一条坏 trace 让后续 retention 全部崩。
        OR IGNORE 仅按 (trace_id, seq) 跳过已存在行，不改写 hash（仍不违 S7）。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT trace_id, seq, phase, payload, prev_hash, curr_hash, created_at "
                "FROM audit_records WHERE trace_id = ? ORDER BY seq ASC",
                (trace_id,),
            ).fetchall()
            dest_conn.executemany(
                "INSERT OR IGNORE INTO audit_records "
                "(trace_id, seq, phase, payload, prev_hash, curr_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        row["trace_id"],
                        row["seq"],
                        row["phase"],
                        row["payload"],
                        row["prev_hash"],
                        row["curr_hash"],
                        row["created_at"],
                    )
                    for row in rows
                ],
            )
            dest_conn.commit()
            return len(rows)

    def delete_trace(self, trace_id: str) -> int:
        """从主库删除一条 trace 的全部 record。返回删除条数。持 self._lock。

        仅供 retention 在归档库 verify valid 后调用（先验后删）。
        """
        with self._lock:
            cur = self._conn.execute("DELETE FROM audit_records WHERE trace_id = ?", (trace_id,))
            self._conn.commit()
            return cur.rowcount

    def db_size_bytes(self) -> int:
        """主库在盘字节数（含 -wal/-shm 边车，反映真实占用）。:memory: 返回 0。

        供 rotation 阈值判断与回收前后对比。读 PRAGMA database_list 取 main 库文件路径
        （:memory: 时该路径为空串）。
        """
        main_file = None
        for row in self._conn.execute("PRAGMA database_list").fetchall():
            if row["name"] == "main":
                main_file = row["file"]
                break
        if not main_file:
            return 0
        total = 0
        for suffix in ("", "-wal", "-shm"):
            sidecar = Path(main_file + suffix)
            if sidecar.exists():
                total += sidecar.stat().st_size
        return total

    def close(self) -> None:
        """关闭底层连接（lifespan shutdown 时由 L 调用）。"""
        self._conn.close()

    @staticmethod
    def _broken(trace_id: str, count: int, seq: int, reason: str) -> ChainVerifyResult:
        return ChainVerifyResult(
            valid=False, trace_id=trace_id, record_count=count, broken_seq=seq, reason=reason
        )
