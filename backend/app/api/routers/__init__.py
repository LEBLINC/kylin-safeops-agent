"""API 路由聚合：把各端点路由合成一个 api_router 供 app 挂载。

聚合顺序无语义依赖；各 router 自带 prefix。
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.routers.approvals import router as approvals_router
from backend.app.api.routers.auth import router as auth_router
from backend.app.api.routers.chat import router as chat_router
from backend.app.api.routers.rca import router as rca_router
from backend.app.api.routers.sessions import router as sessions_router
from backend.app.api.routers.system import router as system_router
from backend.app.api.routers.tools import router as tools_router

api_router = APIRouter()
# sessions 先于 chat 挂载：静态路径 /api/chat/sessions 优先于无关的动态段匹配
api_router.include_router(sessions_router)
api_router.include_router(chat_router)
api_router.include_router(approvals_router)
api_router.include_router(tools_router)
api_router.include_router(system_router)
api_router.include_router(rca_router)
api_router.include_router(auth_router)

__all__ = ["api_router"]
