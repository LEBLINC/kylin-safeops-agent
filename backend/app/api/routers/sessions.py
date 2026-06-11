"""增量5：会话 CRUD（内存版）。

GET/POST /api/chat/sessions（list/create）+ GET/PATCH/DELETE /api/chat/sessions/{id}。
search 后置。会话对象字段对齐 X 前端 ChatSession（session_id 主键）。

路由前缀 /api/chat/sessions 为静态路径，与 chat.py 的 /api/chat/{trace_id}/events
（动态段）不冲突（sessions 路径多一段静态 "sessions"）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.app import get_session_store
from backend.app.api.deps import verify_token
from backend.app.api.schemas import (
    ChatSessionDTO,
    SessionCreateRequest,
    SessionDeleteResponse,
    SessionUpdateRequest,
)
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


@router.get("/{session_id}", response_model=ChatSessionDTO)
async def get_session(
    session_id: str,
    _user: str = Depends(verify_token),
    store: SessionStore = Depends(get_session_store),
) -> ChatSessionDTO:
    """取单个会话；不存在 → 404。"""
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown session_id: {session_id}")
    return session


@router.patch("/{session_id}", response_model=ChatSessionDTO)
async def update_session(
    session_id: str,
    body: SessionUpdateRequest,
    _user: str = Depends(verify_token),
    store: SessionStore = Depends(get_session_store),
) -> ChatSessionDTO:
    """改会话标题；不存在 → 404。"""
    session = store.update_title(session_id, body.title)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown session_id: {session_id}")
    return session


@router.delete("/{session_id}", response_model=SessionDeleteResponse)
async def delete_session(
    session_id: str,
    _user: str = Depends(verify_token),
    store: SessionStore = Depends(get_session_store),
) -> SessionDeleteResponse:
    """删除会话；不存在 → 404。"""
    if not store.delete(session_id):
        raise HTTPException(status_code=404, detail=f"unknown session_id: {session_id}")
    return SessionDeleteResponse(session_id=session_id, deleted=True)
