"""对话会话 CRUD（/api/chat/sessions/*）。

设计要点：
- session_id 主键，跨多次请求长存（前端左侧"对话会话"列表）。
- 内存版 SessionStore（持久化待后续）；单进程 OK。
- L-H1 IDOR 修复：create / get / update / delete 全走 owner 校验（admin 例外）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.app import get_session_store
from backend.app.api.auth import Principal
from backend.app.api.deps import principal_for_idor
from backend.app.api.schemas import (
    ChatSessionDTO,
    SessionCreateRequest,
    SessionDeleteResponse,
    SessionUpdateRequest,
)
from backend.app.api.session_store import (
    SessionForbidden,
    SessionNotFound,
    SessionStore,
)

router = APIRouter(prefix="/api/chat/sessions", tags=["sessions"])


def _store() -> SessionStore:
    return get_session_store()


def _is_admin(principal: Principal) -> bool:
    return "admin" in principal.roles


def _raise_for_session_error(exc: Exception) -> None:
    """L-H1：SessionNotFound / SessionForbidden → HTTP 404 / 403。"""
    if isinstance(exc, SessionNotFound):
        raise HTTPException(status_code=404, detail="session not found") from exc
    if isinstance(exc, SessionForbidden):
        raise HTTPException(status_code=403, detail="forbidden") from exc
    raise exc


@router.post("", response_model=ChatSessionDTO, status_code=status.HTTP_201_CREATED)
def create_session(
    body: SessionCreateRequest,
    principal: Principal = Depends(principal_for_idor),
) -> ChatSessionDTO:
    """L-H1：create 必须传 owner=principal.user（已验证身份）。"""
    return _store().create(body.title, owner=principal.user)


@router.get("", response_model=list[ChatSessionDTO])
def list_sessions(
    principal: Principal = Depends(principal_for_idor),
) -> list[ChatSessionDTO]:
    """L-H1：list 按 owner 过滤；admin 看全。"""
    return _store().list_for(principal.user, is_admin=_is_admin(principal))


@router.get("/{session_id}", response_model=ChatSessionDTO)
def get_session(
    session_id: str,
    principal: Principal = Depends(principal_for_idor),
) -> ChatSessionDTO:
    """L-H1：get 走 assert_owner，404 if not exist / 403 if not owner (非 admin)."""
    try:
        return _store().assert_owner(session_id, principal.user, is_admin=_is_admin(principal))
    except (SessionNotFound, SessionForbidden) as e:
        _raise_for_session_error(e)
        raise AssertionError("unreachable: _raise_for_session_error raises") from None


@router.patch("/{session_id}", response_model=ChatSessionDTO)
def update_session(
    session_id: str,
    body: SessionUpdateRequest,
    principal: Principal = Depends(principal_for_idor),
) -> ChatSessionDTO:
    """L-H1：update 走 assert_owner + 改 title。"""
    store = _store()
    try:
        store.assert_owner(session_id, principal.user, is_admin=_is_admin(principal))
    except (SessionNotFound, SessionForbidden) as e:
        _raise_for_session_error(e)
    updated = store.update_title(session_id, body.title)
    if updated is None:
        raise HTTPException(status_code=404, detail="session disappeared")
    return updated


@router.delete("/{session_id}", response_model=SessionDeleteResponse)
def delete_session(
    session_id: str,
    principal: Principal = Depends(principal_for_idor),
) -> SessionDeleteResponse:
    """L-H1：delete 走 assert_owner + 删。"""
    store = _store()
    try:
        store.assert_owner(session_id, principal.user, is_admin=_is_admin(principal))
    except (SessionNotFound, SessionForbidden) as e:
        _raise_for_session_error(e)
    deleted = store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session disappeared")
    return SessionDeleteResponse(session_id=session_id, deleted=True)
