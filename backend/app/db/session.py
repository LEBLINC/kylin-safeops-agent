"""SQLite 连接工厂 + 审计表 schema（标准库 sqlite3，零新依赖）。

LoongArch 无 C 扩展风险：sqlite3 为 CPython 内置。
连接持有方式：check_same_thread=False，跨线程复用由持有方（SqliteAuditSink）
用一把 threading.Lock 串行写入；WAL 模式提升读写并发。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

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
    return conn
