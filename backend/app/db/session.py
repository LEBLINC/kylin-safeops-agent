"""SQLite 连接工厂 + 审计表 schema（标准库 sqlite3，零新依赖）。

LoongArch 无 C 扩展风险：sqlite3 为 CPython 内置。
连接持有方式：check_same_thread=False，跨线程复用由持有方（SqliteAuditSink）
用一把 threading.Lock 串行写入；WAL 模式提升读写并发。
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_AUDIT_DB = "./data/audit.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id    TEXT    NOT NULL,
    seq         INTEGER NOT NULL,
    phase       TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    prev_hash   TEXT    NOT NULL,
    curr_hash   TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    UNIQUE (trace_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_audit_records_trace_seq ON audit_records (trace_id, seq);
"""


def resolve_audit_db_path(raw: str | None, *, require_absolute: bool) -> str:
    """解析审计库路径（纯函数，供 L 在 app.py 接线调用）。

    - raw None/空白 → 默认 ./data/audit.db（dev 友好，零回归）；调用方应 log WARN
      「dev 默认路径，生产须设 KYLIN_AUDIT_DB 绝对路径」。
    - raw == ":memory:" → 原样返回（短路，不做绝对路径校验；保护测试夹具）。
    - require_absolute=True 且 raw 非绝对 → raise ValueError（fail-closed，拒启动，
      绝不静默落 cwd）。require_absolute 由 L 按 KYLIN_AUTH_MODE=="proxy" 计算后传入。
    - 其余 → os.path.realpath 规范化返回。
    """
    if raw is None or not raw.strip():
        return _DEFAULT_AUDIT_DB
    raw = raw.strip()
    if raw == ":memory:":
        return raw
    if require_absolute and not os.path.isabs(raw):
        raise ValueError(
            "生产模式（KYLIN_AUTH_MODE=proxy）要求 KYLIN_AUDIT_DB 为绝对路径，"
            f"实得相对路径: {raw!r}"
        )
    return os.path.realpath(raw)


def _secure_perms(db_path: str | Path) -> None:
    """审计库受限权限：文件 0600 / 父目录 0700 / WAL 边车 0600。

    :memory: 短路跳过（保护 conftest 夹具）。chmod 仅属主有效；失败（多用户/属主不符，
    如 VM 那次 root 先起 app）log 清晰错误但不抛——落库已成功，权限是加固层，
    属主真解在部署层（systemd User=<agent 用户> + 审计目录归该用户）。
    """
    p = str(db_path)
    if p == ":memory:":
        return
    path = Path(p)
    try:
        os.chmod(path, 0o600)
        os.chmod(path.parent, 0o700)
        for name in (path.name + "-wal", path.name + "-shm"):
            sidecar = path.with_name(name)
            if sidecar.exists():
                os.chmod(sidecar, 0o600)
    except OSError as exc:
        logger.error(
            "审计库权限加固失败（chmod）: %s ── 多为属主不符/多用户起 app。"
            "部署须保证审计目录归 agent 运行用户所有（systemd User=）。err=%r",
            path,
            exc,
        )


def connect(db_path: str | Path = ":memory:") -> sqlite3.Connection:
    """打开 SQLite 连接并保证 schema 就绪（幂等建表）。

    默认 :memory:（测试友好）；文件路径时自动创建父目录。
    check_same_thread=False：FastAPI 线程池可能跨线程调用，
    写入串行化由 SqliteAuditSink 的锁负责。
    """
    if db_path != ":memory:":
        parent = Path(db_path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    if db_path != ":memory:":
        _secure_perms(db_path)  # 文件已建，设受限权限（:memory: 经此守卫天然跳过）
    return conn
