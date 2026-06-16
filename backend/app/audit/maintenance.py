"""审计库 retention/rotation（决策⑪ 3b）。带外 CLI，不进 app。

设计铁律：
- 终态闸：只归档含 FINISHED/REJECTED 终态记录的 trace（in-flight 一律不归档）。
- 时间缓冲：叠加 RETENTION_DAYS，trace 最新记录须早于 N 天前。两条件 AND。
- 按 trace 整批搬迁，绝不按 record 删（删一条破哈希链）。
- 先验后删：export → 归档库 verify_chain valid → 才从主库 DELETE；verify 失败保守不删。
- 确定性：now 由 CLI 注入（now_iso），run_retention / _archive_db_path 不在函数内取 now，
  使单测可钉死时间（符合 D 的确定性铁律）。
- 不改 append 的 hash 语义（S7）、不改 verify_chain 复算逻辑、不改 schema。
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.audit.audit_logger import SqliteAuditSink

logger = logging.getLogger(__name__)

_DEFAULT_RETENTION_DAYS = 90
_DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100MB


@dataclass
class RetentionReport:
    """一次 retention/rotation 的结果（确定性、可打印、可断言）。"""

    archived_traces: list[str]
    archived_records: int
    freed_bytes: int
    main_db_bytes_after: int
    skipped_in_flight: int  # 因未达终态而跳过的 trace 数
    archive_db_path: str | None


def _before_iso(now_iso: str, retention_days: int) -> str:
    """时间缓冲下界：now - retention_days（保持与 created_at 同为 ISO/UTC，可词法比较）。"""
    cutoff = datetime.fromisoformat(now_iso) - timedelta(days=retention_days)
    return cutoff.isoformat()


def _archive_db_path(main_db_path: str, archive_dir: str | None, now_iso: str) -> Path:
    """归档库路径：archive_dir（默认主库同目录）/audit.archive.YYYYMM.db。

    YYYYMM 取自注入的 now_iso（不在函数内 new datetime，保持确定性）。
    """
    yyyymm = datetime.fromisoformat(now_iso).strftime("%Y%m")
    base = Path(archive_dir) if archive_dir else Path(main_db_path).resolve().parent
    return base / f"audit.archive.{yyyymm}.db"


def run_retention(
    main_db_path: str,
    *,
    retention_days: int,
    max_bytes: int,
    archive_dir: str | None,
    now_iso: str,
) -> RetentionReport:
    """对主库执行 retention/rotation，返回 RetentionReport。

    1. before_iso = now - retention_days；候选 = iter_closed_traces(before_iso)。
    2. 若 db_size <= max_bytes 且无候选 → 空 report 直接返回（无操作，不建归档库）。
    3. 对每个候选 trace（先验后删）：
       export_trace → 归档库 → 临时 sink verify_chain valid → delete_trace；
       verify 失败则跳过该 trace + log error（保守不删，宁可留主库不破链）。
    4. 有归档 → 主库 VACUUM（事务外）+ wal_checkpoint(TRUNCATE) 回收空间。

    绝不按 record 删；绝不归档无终态 trace。:memory: 无意义，直接拒。
    """
    if not main_db_path or not main_db_path.strip() or main_db_path.strip() == ":memory:":
        raise ValueError(
            f"retention 仅对文件库有意义，拒绝 main_db_path={main_db_path!r}（:memory:/空）"
        )

    sink = SqliteAuditSink(main_db_path)
    try:
        before_bytes = sink.db_size_bytes()
        before_iso = _before_iso(now_iso, retention_days)
        candidates = sink.iter_closed_traces(before_iso=before_iso)
        skipped_in_flight = sink.count_in_flight_traces()

        if not candidates and before_bytes <= max_bytes:
            return RetentionReport(
                archived_traces=[],
                archived_records=0,
                freed_bytes=0,
                main_db_bytes_after=before_bytes,
                skipped_in_flight=skipped_in_flight,
                archive_db_path=None,
            )

        archived_traces: list[str] = []
        archived_records = 0
        archive_db_path: str | None = None

        if candidates:
            archive_path = _archive_db_path(main_db_path, archive_dir, now_iso)
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            archive_sink = SqliteAuditSink(str(archive_path))
            try:
                for trace_id in candidates:
                    # 先验后删：拷进归档库 → 归档库 verify valid → 才删主库。
                    # 注：候选均为终态(已闭合)trace，编排层不会再 append；
                    # export/delete 各自持 self._lock（不可重入锁，故不在此再套外层锁）。
                    sink.export_trace(trace_id, archive_sink._conn)
                    result = archive_sink.verify_chain(trace_id)
                    if not result.valid:
                        logger.error(
                            "归档库 verify 失败，保守跳过不删主库: trace=%s reason=%s",
                            trace_id,
                            result.reason,
                        )
                        continue
                    archived_records += sink.delete_trace(trace_id)
                    archived_traces.append(trace_id)
            finally:
                archive_sink.close()
            archive_db_path = str(archive_path)

        if archived_traces:
            # VACUUM 不能在事务内：先 commit，再独立执行；wal_checkpoint(TRUNCATE) 截断边车。
            sink._conn.commit()
            sink._conn.execute("VACUUM")
            sink._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        after_bytes = sink.db_size_bytes()
        return RetentionReport(
            archived_traces=archived_traces,
            archived_records=archived_records,
            freed_bytes=max(before_bytes - after_bytes, 0),
            main_db_bytes_after=after_bytes,
            skipped_in_flight=skipped_in_flight,
            archive_db_path=archive_db_path,
        )
    finally:
        sink.close()


def _env_int(name: str, default: int) -> int:
    """读 env 整数；未设/空白用默认；设了但非法 → ValueError（fail-loud）。"""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _format_report(report: RetentionReport) -> str:
    lines = [
        "audit retention/rotation 完成：",
        f"  归档 trace 数        : {len(report.archived_traces)}",
        f"  归档记录条数         : {report.archived_records}",
        f"  跳过(未达终态) trace : {report.skipped_in_flight}",
        f"  回收字节             : {report.freed_bytes}",
        f"  主库现大小(字节)     : {report.main_db_bytes_after}",
        f"  归档库               : {report.archive_db_path or '(无归档)'}",
    ]
    if report.archived_traces:
        lines.append(f"  归档 trace_id        : {', '.join(report.archived_traces)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：python -m backend.app.audit.maintenance

    读 env：KYLIN_AUDIT_DB（必须，拒 :memory:/拒空）、KYLIN_AUDIT_RETENTION_DAYS(默认90)、
    KYLIN_AUDIT_MAX_BYTES(默认 100MB)、KYLIN_AUDIT_ARCHIVE_DIR(可选)。
    now_iso 在此取（datetime.now(UTC).isoformat()）后注入 run_retention（确定性边界）。
    打印 RetentionReport 返回 0；参数非法/run_retention raise 则打错误返回 1。
    """
    raw_db = os.environ.get("KYLIN_AUDIT_DB", "")
    if not raw_db.strip() or raw_db.strip() == ":memory:":
        print(
            "ERROR: KYLIN_AUDIT_DB 未设或为 :memory:；maintenance 仅对文件库有意义。",
            file=sys.stderr,
        )
        return 1

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        retention_days = _env_int("KYLIN_AUDIT_RETENTION_DAYS", _DEFAULT_RETENTION_DAYS)
        max_bytes = _env_int("KYLIN_AUDIT_MAX_BYTES", _DEFAULT_MAX_BYTES)
        archive_dir = os.environ.get("KYLIN_AUDIT_ARCHIVE_DIR") or None
        report = run_retention(
            raw_db.strip(),
            retention_days=retention_days,
            max_bytes=max_bytes,
            archive_dir=archive_dir,
            now_iso=now_iso,
        )
    except Exception as exc:
        # CLI 边界：任何失败转退出码 1 + stderr（带外运维脚本不应抛栈给 cron）。
        print(f"ERROR: retention 失败: {exc!r}", file=sys.stderr)
        return 1

    print(_format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
