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
from backend.app.contracts.policy import PolicyEngine
from backend.app.db.session import connect as _db_connect
from backend.app.db.session import resolve_audit_db_path
from backend.app.llm.adapter import LLMAdapter
from backend.app.mcp.gateway import MCPGateway
from backend.app.security.guard import RuleBasedPolicyEngine
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
    """获取 LLMAdapter。

    阶段5 step 2 收口 (ADR-0006 real-mode-by-default, 2026-07-14):
    默认真接 LLM (RealLLMClient); KYLIN_LLM_FAKE=true 显式 opt-in 回 fake;
    KYLIN_LLM_RECORD=true 仍走真接 (录制场景兼容)。
    ADR-0003 demo-only 已退役(留兼容注释)。生产 KYLIN_LLM_FAKE 永远 false。
    """
    from backend.app.llm.adapter import LLMAdapter as _LLMAdapter
    from backend.app.llm.real_client import (
        RealLLMClient,  # 延迟导入,未用不付出 import 成本
        load_real_llm_config_from_env,
    )

    if os.environ.get("KYLIN_LLM_FAKE", "").strip().lower() == "true":
        # 显式 opt-in 回 fake (演示 / 单测用)
        return build_fake_llm()

    # 默认走真接 (含 KYLIN_LLM_RECORD=true 录制场景兼容)
    # X P5 fix: summary_fn 注入 real.summarize (否则走 _default_summary_fn 兜底)
    real = RealLLMClient(load_real_llm_config_from_env())
    return _LLMAdapter(completion_fn=real.completion_fn, summary_fn=real.summarize)


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


def get_policy() -> PolicyEngine:
    """获取 PolicyEngine（commit 3 增量：/api/policy/* 用）。

    当前无全局单例——build_gateway 在 lifespan 内注入的是另一个实例。
    此处新建一份独立实例给 policy router 用（策略集是 DEFAULT_POLICY，
    确定性无 IO，多份实例与单实例语义等价；生产场景可后续统一从 gateway 取）。
    测试可经 dependency_overrides[get_policy] 注入覆盖。
    """
    return RuleBasedPolicyEngine()


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

    # ADR-0004：proxy + mock 误启硬阻断。lifespan 启动期 raise → systemd
    # 把服务拉成 failed，运维立即看到告警。dev 模式放行（demo/单测需要 mock）。
    # 双保险：systemd Environment=KYLIN_LDAP_MOCK=false 硬编码 + install.sh 写
    # /etc/kylin-safeops/agent.env。任意一处生效即可拒启动；本 fail-fast 是第三道兜底。
    if _auth_mode() == "proxy" and os.environ.get("KYLIN_LDAP_MOCK", "").strip().lower() == "true":
        raise RuntimeError(
            "ADR-0004：proxy 模式拒绝 KYLIN_LDAP_MOCK=true——mock LDAP 仅允许 demo/单测。"
            " 生产必须 KYLIN_LDAP_MOCK=false + 真 LDAP；请检查 systemd Environment / "
            "/etc/kylin-safeops/agent.env 配置。"
        )

    _bus = EventBus()
    _registry = SessionRegistry()
    _gateway = build_gateway()
    _session_store = SessionStore()
    # 审计落库单例：真 SqliteAuditSink 持 DB 句柄 + 链状态，必须单例（决策2：真执行=真审计同批）。
    # fail_closed 接线（D 域 7b74404/94bdac9 已就位 connect(fail_closed=...) + 测试）：
    #   - proxy 模式（生产）→ fail_closed=True（chmod 失败 raise，拒启动）；
    #   - dev 模式（联调）→ fail_closed=False（chmod 失败仅 log，不抛）。
    # 复用模块级 _AUDIT_DB_PATH（conftest 可 setattr 钉 :memory:；文件路径时由模块级
    # resolve_audit_db_path 在 import 期算 require_absolute → proxy 下相对路径已 fail-closed）。
    # 本处只在 SqliteAuditSink 构造前显式 connect() 一次，把 fail_closed 一并传入；SqliteAuditSink
    # 内部若收到 str/Path 还会再调 connect(无 fail_closed)——故提前 connect 拿 conn 再传。
    # 注意：_db_connect 是 module-level（顶部 import），让测试可 spy app._db_connect
    # （不要在 lifespan 内部重新 import，否则 spy 不生效）。
    _auth_mode_now = _auth_mode()
    _fail_closed = _auth_mode_now == "proxy"
    if str(_AUDIT_DB_PATH) == ":memory:":
        # 测试夹具：直接传 :memory:，让 SqliteAuditSink 内部 connect 时自动跳 _secure_perms
        _audit = SqliteAuditSink(db=_AUDIT_DB_PATH)
    else:
        # 文件路径：先 connect 一次（带 fail_closed），把 conn 传给 SqliteAuditSink 复用
        _audit_conn = _db_connect(_AUDIT_DB_PATH, fail_closed=_fail_closed)
        _audit = SqliteAuditSink(db=_audit_conn)
        logger.info(
            "审计库已连接（auth_mode=%s, fail_closed=%s, path=%s）",
            _auth_mode_now,
            _fail_closed,
            _AUDIT_DB_PATH,
        )
    _cleanup_task = asyncio.create_task(_periodic_cleanup())

    # B4 commit 2 L-H16: setup_logging 注入 JSON / console formatter
    from backend.app.main_logging import setup_logging

    setup_logging()
    logger.info("API layer initialized: bus=%s, registry=%s", _bus, _registry)

    yield

    # L-B4-2：lifespan shutdown 顺序 drain（架构整改 H6）。
    # 顺序：registry → bus → audit → session_store
    #   - registry 先停：避免新 task 启动（防与 drain 抢锁）
    #   - bus 收尾：清理 queue
    #   - audit 落盘：flush + close（防 WAL 数据丢）
    #   - session_store 末尾：会话表落库
    # S8 兜底：drain 阶段每步 try/except + logger.warning + 继续后续（不杀状态机）
    _DRAIN_TIMEOUT = 10.0  # 秒

    # 阶段 1：停 _cleanup_task
    if _cleanup_task is not None:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 S8
            pass

    # 阶段 2：drain registry（等待所有 RUNNING orchestrator task 完成）
    if _registry is not None:
        try:
            running = [
                s.task
                for s in _registry.snapshot()
                if not s.is_done and s.task is not None and not s.task.done()
            ]
            if running:
                logger.info(
                    "lifespan shutdown: draining %d running orchestrator tasks", len(running)
                )
                done, pending = await asyncio.wait(running, timeout=_DRAIN_TIMEOUT)
                for t in pending:
                    t.cancel()
                for t in pending:
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):  # noqa: BLE001 S8
                        pass
        except Exception:  # noqa: BLE001 S8
            logger.exception("lifespan shutdown: registry drain 阶段异常（继续）")

    # 阶段 3：drain bus（清空 queue）
    if _bus is not None:
        try:
            drained = _bus.drain_all()
            logger.info("lifespan shutdown: bus drain 移除 %d 个空 queue", drained)
        except Exception:  # noqa: BLE001 S8
            logger.exception("lifespan shutdown: bus drain 阶段异常（继续）")

    # 阶段 4：audit flush + close（防 WAL 数据丢）
    if _audit is not None:
        try:
            # L-B4-3：checkpoint WAL 数据到主库
            _audit.flush()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 S8
            logger.exception("lifespan shutdown: audit flush 阶段异常（继续）")
        try:
            _audit.close()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 S8
            logger.exception("lifespan shutdown: audit close 阶段异常（继续）")

    # 阶段 5：session_store 落库（如有）
    if _session_store is not None:
        try:
            # SessionStore 无显式 close；此处预留钩子给未来 DB 落盘
            pass
        except Exception:  # noqa: BLE001 S8
            logger.exception("lifespan shutdown: session_store 阶段异常（继续）")

    # 阶段 6：清理全局引用
    _bus = None
    _registry = None
    _gateway = None
    _session_store = None
    _audit = None
    _cleanup_task = None
    logger.info("API layer shutdown complete (L-B4-2 顺序 drain 完毕)")


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

    # B4 commit 2 L-H16: trace_id contextvar middleware
    from backend.app.api.middleware import TraceIdMiddleware

    app.add_middleware(TraceIdMiddleware)

    # B5 commit 2 L-M5: 请求体大小上限 (Content-Length gate; chunked 增量后续)
    from backend.app.api.middleware import RequestSizeLimitMiddleware

    app.add_middleware(RequestSizeLimitMiddleware)

    # B5 P3 (L-M5 chunked path): ASGI 守门 wrap receive 累计 (chunked 路径)
    from backend.app.api.middleware import ASGIMaxBodySizeMiddleware

    app.add_middleware(ASGIMaxBodySizeMiddleware)

    # 路由挂载：延迟 import 避免 routers ↔ app 循环依赖
    # （routers 从本模块 import get_bus/get_registry/... 作 Depends）。
    from backend.app.api.routers import api_router

    app.include_router(api_router)

    return app


# ADR-0006 阶段5 step 2 收口 (2026-07-14)
# default 真接 LLM;ADR-0003 退役;KYLIN_LLM_FAKE=true 显式 opt-in
