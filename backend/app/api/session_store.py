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


class SessionNotFound(LookupError):
    """session_id 不存在（L-H1 IDOR fail-closed 404）。"""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"session {session_id} not found")
        self.session_id = session_id


class SessionForbidden(PermissionError):
    """会话存在但 caller 非 owner 且非 admin（L-H1 IDOR fail-closed 403）。"""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"session {session_id} not accessible")
        self.session_id = session_id


class SessionStore:
    """内存对话会话表，按 session_id 索引。"""

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSessionDTO] = {}

    def create(self, title: str | None = None, *, owner: str) -> ChatSessionDTO:
        """新建会话，自动生成 session_id 与时间戳；owner 必填（L-H1 IDOR 修复）。"""
        session_id = uuid.uuid4().hex
        now = _now_iso()
        session = ChatSessionDTO(
            session_id=session_id,
            title=title or "新会话",
            created_at=now,
            updated_at=now,
            owner=owner,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> ChatSessionDTO | None:
        """按 id 取会话。"""
        return self._sessions.get(session_id)

    def list_for(self, principal_user: str, is_admin: bool) -> list[ChatSessionDTO]:
        """L-H1：列会话按 owner 过滤；admin 看到全部。"""
        all_sess = sorted(self._sessions.values(), key=lambda s: s.updated_at, reverse=True)
        if is_admin:
            return all_sess
        return [s for s in all_sess if s.owner == principal_user]

    def assert_owner(self, session_id: str, principal_user: str, is_admin: bool) -> ChatSessionDTO:
        """L-H1：owner 校验。fail-closed 抛 SessionNotFound 或 SessionForbidden。

        - session_id 不存在 → SessionNotFound（404）
        - owner 不匹配且非 admin → SessionForbidden（403）
        - owner 匹配 / admin role → 返 ChatSessionDTO
        """
        sess = self._sessions.get(session_id)
        if sess is None:
            raise SessionNotFound(session_id)
        if is_admin or sess.owner == principal_user:
            return sess
        raise SessionForbidden(session_id)

    def touch(self, session_id: str) -> None:
        """更新会话的 updated_at（有新请求时调用）；不存在则忽略。"""
        session = self._sessions.get(session_id)
        if session is not None:
            session.updated_at = _now_iso()

    def update_title(self, session_id: str, title: str) -> ChatSessionDTO | None:
        """改会话标题并刷新 updated_at；不存在返回 None。"""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        session.title = title
        session.updated_at = _now_iso()
        return session

    def delete(self, session_id: str) -> bool:
        """删除会话；存在并删除返回 True，不存在返回 False。"""
        return self._sessions.pop(session_id, None) is not None
