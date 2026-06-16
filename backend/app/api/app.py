"""FastAPI 应用骨架 + lifespan + fake 装配。

增量1 职责：
- 创建 FastAPI 实例，挂载全局中间件（CORS 联调用）。
- lifespan 中初始化全局单例（EventBus、SessionRegistry、MCPGateway fake 装配）。
- 提供 get_bus / get_registry / get_gateway 供路由层 Depends 获取。
- 启动日志显式标注认证姿态（proxy 全量签名身份 / dev 联调放行）。

安全红线：
- 所有端点经 verify_token 依赖认证（proxy 模式 fail-closed / dev 联调放行）。
- CORS 仅联调期开放，部署时须收紧。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.agent.ports import AuditSink
from backend.app.agent.rca import RCAEngine
from backend.app.api._fakes import build_fake_llm, build_gateway
from backend.app.api.event_bus import EventBus
from backend.app.api.session_registry import SessionRegistry
from backend.app.api.session_store import SessionStore
from backend.app.audit import SqliteAuditSink
from backend.app.db.session import resolve_audit_db_path
from backend.app.llm.adapter import LLMAdapter
from backend.app.mcp.gateway import MCPGateway
from mcp_servers.rca import DefaultRCAEngine

logger = logging.getLogger(__name__)

#: 审计库落库路径（L 域配置常量，决策⑪ 3a）。
#: proxy 模式（生产）：KYLIN_AUDIT_DB 必须是绝对路径，否则 fail-closed（拒启动）。
#: dev 模式：未设 env 则默认 ./data/audit.db（零回归）。
_require_abs = os.environ.get("KYLIN_AUTH_MODE", "proxy").strip().lower() == "proxy"
_AUDIT_DB_PATH = resolve_audit_db_path(
    os.environ.get("KYLIN_AUDIT_DB"), require_absolute=_require_abs
)
if _AUDIT_DB_PATH == "./data/audit.db":
    logger.warning("审计库使用 dev 默认路径（./data/audit.db）——生产须设 KYLIN_AUDIT_DB 绝对路径")

# ============================================================
# 全局单例（lifespan 中初始化，路由层通过 Depends 获取）
# ============================================================

_bus: EventBus | None = None
_registry: SessionRegistry | None = None
_gateway: MCPGateway | None = None
_session_store: SessionStore | None = None
_audit: AuditSink | None = None
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


def get_session_store() -> SessionStore:
    """获取全局 SessionStore 实例（对话会话表）。"""
    assert _session_store is not None, "SessionStore not initialized (lifespan not started)"
    return _session_store


def get_llm() -> LLMAdapter:
    """获取 LLMAdapter（当前为 fake 注入桩，待接真实 LLM 端点）。

    非单例：每次装配一个 fake；测试可经 dependency_overrides 替换。
    """
    return build_fake_llm()


def get_audit() -> AuditSink:
    """获取 AuditSink 单例（已接 D 的真 SqliteAuditSink，lifespan 初始化）。

    **必须单例**：真 sink 持 DB 句柄 + 链状态（_seq/_prev_hash 由 orchestrator 实例内存续写，
    但落库连接全局共享），per-request 新建会丢链/重复建连接。
    测试可经 dependency_overrides[get_audit] 注入 SqliteAuditSink(":memory:") 覆盖。
    """
    assert _audit is not None, "AuditSink not initialized (lifespan not started)"
    return _audit


def get_rca() -> RCAEngine:
    """获取 RCAEngine（已接 X 的 mcp_servers/rca.DefaultRCAEngine）。

    非单例：DefaultRCAEngine 是无状态确定性规则引擎（不执行命令、不改系统、不持句柄），
    每请求新建即可。注入 Orchestrator 后，一条 chat 链跑完若产非空报告即 emit "rca" 事件；
    独立 RCA 端点（routers/rca.py）亦消费同一引擎。
    """
    return DefaultRCAEngine()


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
    global _bus, _registry, _gateway, _session_store, _audit, _cleanup_task  # noqa: PLW0603

    from backend.app.api.deps import _auth_mode

    if _auth_mode() == "dev":
        logger.warning(
            "╔══════════════════════════════════════════════════╗\n"
            "║  DEV 认证模式：全量端点联调放行、审批角色取自    ║\n"
            "║  裸 X-User-Role（可伪造）——仅限内网/联调，严禁生产！║\n"
            "╚══════════════════════════════════════════════════╝"
        )
    else:
        logger.info(
            "认证模式 PROXY：全量端点要求反代签名身份（fail-closed 401）；"
            "审批角色取自反代签名头。须由可信反代对所有入站请求注入签名身份头。"
        )

    _bus = EventBus()
    _registry = SessionRegistry()
    _gateway = build_gateway()
    _session_store = SessionStore()
    # 审计落库单例：真 SqliteAuditSink 持 DB 句柄 + 链状态，必须单例（决策2：真执行=真审计同批）。
    _audit = SqliteAuditSink(db=_AUDIT_DB_PATH)
    _cleanup_task = asyncio.create_task(_periodic_cleanup())

    logger.info("API layer initialized: bus=%s, registry=%s", _bus, _registry)

    yield

    # Shutdown
    if _cleanup_task is not None:
        _cleanup_task.cancel()
    if _audit is not None:
        _audit.close()  # type: ignore[attr-defined]  # SqliteAuditSink 持 DB 句柄需显式关闭
    _bus = None
    _registry = None
    _gateway = None
    _session_store = None
    _audit = None
    logger.info("API layer shutdown complete")


# ============================================================
# FastAPI 实例
# ============================================================


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(
        title="Kylin SafeOps Agent",
        description="安全智能运维 Agent API（proxy 模式全量端点要求反代签名身份 / dev 联调放行）",
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

    # 路由挂载：延迟 import 避免 routers ↔ app 循环依赖
    # （routers 从本模块 import get_bus/get_registry/... 作 Depends）。
    from backend.app.api.routers import api_router

    app.include_router(api_router)

    return app
