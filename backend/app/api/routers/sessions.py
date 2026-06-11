"""增量5：会话 CRUD（内存版 list/create）。

GET/POST /api/chat/sessions。PATCH/DELETE/search/单个 GET 后置（留待后续增量）。
会话对象字段对齐 X 前端 ChatSession（session_id 主键）。

路由前缀 /api/chat/sessions 为静态路径，与 chat.py 的 /api/chat/{trace_id}/events
（动态段）不冲突。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.app import get_session_store
from backend.app.api.deps import verify_token
from backend.app.api.schemas import ChatSessionDTO, SessionCreateRequest
from backend.app.api.session_store import SessionStore

router = APIRouter(prefix="/api/chat/sessions", tags=["sessions"])


@router.get("", response_model=list[ChatSessionDTO])
async def list_sessions(
    _user: str = Depends(verify_token),
    store: SessionStore = Depends(get_session_store),
) -> list[ChatSessionDTO]:
    """列出所有对话会话（最近更新在前）。"""
    return store.list()


@router.post("", response_model=ChatSessionDTO)
async def create_session(
    body: SessionCreateRequest,
    _user: str = Depends(verify_token),
    store: SessionStore = Depends(get_session_store),
) -> ChatSessionDTO:
    """新建对话会话。"""
    return store.create(title=body.title)
