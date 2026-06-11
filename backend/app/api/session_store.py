"""对话会话存储（内存版）。

与 SessionRegistry 严格区分：
- SessionStore（本模块）：前端左侧"对话会话"列表，session_id 主键，跨多次请求长存。
- SessionRegistry：单次 run 的存活 Orchestrator 实例，trace_id 主键，终态后清理。

字段对齐 X 前端 ChatSession（session_id / title / created_at / updated_at）。
TODO: 持久化（DB）归后续；本轮内存版让前端 CRUD 能联调。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.app.api.schemas import ChatSessionDTO


def _now_iso() -> str:
    """当前时间 ISO 字符串（UTC）。"""
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """内存对话会话表，按 session_id 索引。"""

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSessionDTO] = {}

    def create(self, title: str | None = None) -> ChatSessionDTO:
        """新建会话，自动生成 session_id 与时间戳。"""
        session_id = uuid.uuid4().hex
        now = _now_iso()
        session = ChatSessionDTO(
            session_id=session_id,
            title=title or "新会话",
            created_at=now,
            updated_at=now,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> ChatSessionDTO | None:
        """按 id 取会话。"""
        return self._sessions.get(session_id)

    def list(self) -> list[ChatSessionDTO]:
        """返回所有会话，按更新时间倒序（最近在前）。"""
        return sorted(self._sessions.values(), key=lambda s: s.updated_at, reverse=True)

    def touch(self, session_id: str) -> None:
        """更新会话的 updated_at（有新请求时调用）；不存在则忽略。"""
        session = self._sessions.get(session_id)
        if session is not None:
            session.updated_at = _now_iso()
