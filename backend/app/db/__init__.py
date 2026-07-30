"""数据库层：SQLite 连接与审计表 schema（标准库 sqlite3，零新依赖）。"""

from backend.app.db.session import connect

__all__ = ["connect"]
