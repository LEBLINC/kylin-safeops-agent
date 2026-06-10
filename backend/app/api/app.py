"""FastAPI 应用骨架 + lifespan + fake 装配。

增量1 职责：
- 创建 FastAPI 实例，挂载全局中间件（CORS 联调用）。
- lifespan 中初始化全局单例（EventBus、SessionRegistry、MCPGateway fake 装配）。
- 提供 get_bus / get_registry / get_gateway 供路由层 Depends 获取。
- 启动日志显式标注"认证未接入，仅限内网/联调"。

安全红线：
- 所有端点预留 verify_token 依赖（路由层加，此处只建框架）。
- CORS 仅联调期开放，部署时须收紧。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api._fakes import build_fake_gateway
from backend.app.api.event_bus import EventBus
from backend.app.api.session_registry import SessionRegistry
from backend.app.mcp.gateway import MCPGateway

logger = logging.getLogger(__name__)

# ============================================================
# 全局单例（lifespan 中初始化，路由层通过 Depends 获取）
# ============================================================

_bus: EventBus | None = None
_registry: SessionRegistry | None = None
_gateway: MCPGateway | None = None
_cleanup_task: asyncio.Task | None = None  # type: ignore[type-arg]


def get_bus() -> EventBus:
    """获取全局 EventBus 实例。"""
    assert _bus is not None, "EventBus not initialized (lifespan not started)"
    return _bus


def get_registry() -> SessionRegistry:
    """获取全局 SessionRegistry 实例。"""
    assert _registry is not None, "SessionRegistry not initialized (lifespan not started)"
    return _registry


def get_gateway() -> MCPGateway:
    """获取全局 MCPGateway 实例（含已注册工具的 fake 装配）。"""
    assert _gateway is not None, "MCPGateway not initialized (lifespan not started)"
    return _gateway


# ============================================================
# 定期清理过期会话（防内存泄漏）
# ============================================================

_CLEANUP_INTERVAL: float = 60.0  # 秒


async def _periodic_cleanup() -> None:
    """后台任务：定期清理终态超时会话 + 移除对应 EventBus 队列。

    session 与 queue 同生命周期：cleanup_expired 返回被清理的 trace_id 列表，
    逐个 bus.remove，防 queue 永驻泄漏。
    """
    assert _registry is not None
    assert _bus is not None
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL)
        try:
            removed = _registry.cleanup_expired()
            for tid in removed:
                _bus.remove(tid)
            if removed:
                logger.info("session cleanup: removed %d expired sessions", len(removed))
        except Exception:  # noqa: BLE001
            logger.exception("session cleanup error")


# ============================================================
# Lifespan（FastAPI 生命周期管理）
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：初始化全局单例，启动清理任务。"""
    global _bus, _registry, _gateway, _cleanup_task  # noqa: PLW0603

    logger.warning(
        "╔══════════════════════════════════════════════════╗\n"
        "║  认证未接入，仅限内网/联调环境使用              ║\n"
        "║  TODO(BLOCKED-ON-D): 接 D 的 RBAC 模块        ║\n"
        "╚══════════════════════════════════════════════════╝"
    )

    _bus = EventBus()
    _registry = SessionRegistry()
    _gateway = build_fake_gateway()
    _cleanup_task = asyncio.create_task(_periodic_cleanup())

    logger.info("API layer initialized: bus=%s, registry=%s", _bus, _registry)

    yield

    # Shutdown
    if _cleanup_task is not None:
        _cleanup_task.cancel()
    _bus = None
    _registry = None
    _gateway = None
    logger.info("API layer shutdown complete")


# ============================================================
# FastAPI 实例
# ============================================================


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(
        title="Kylin SafeOps Agent",
        description="安全智能运维 Agent API（认证未接入，仅限内网/联调）",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS：联调期开放。
    # 注意：allow_origins=["*"] 与 allow_credentials=True 不能并存（Starlette 会忽略凭证），
    # 故联调保留 "*" 但 allow_credentials=False。
    # TODO: 部署时换具体 origin（前端实际域名）+ 收紧 methods/headers，并按需开 credentials。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app
