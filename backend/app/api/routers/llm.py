"""GET /api/llm/health（健康检查端点，含 ?probe=true 连通性探测）。

设计红线：
1. 默认（无 probe 参数）→ 只报配置态，绝不发 httpx。
2. ?probe=true + fixture → probe_status="skipped"（fixture 无真端点）。
3. ?probe=true + real → 真发一次轻量 POST（独立 budget，不走 _RateLimiter / _TokenCounter）。
4. S9：api_key 只报 bool；probe_error 只报 status_code / error class，不暴露原文。
5. probe 失败时不 raise（运维友好：标 failed/timeout，不崩服务）。
6. probe 失败/超时时落 SqliteAuditSink（phase=probe_failed）+ emit SSE audit_appended
   让前端可见运维历史（决策⑨ mode-aware 守门：审计 + SSE 同步双写）。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.app.agent.ports import AuditSink
from backend.app.api.app import get_audit, get_bus
from backend.app.api.deps import verify_token
from backend.app.api.event_bus import EventBus, sse_stream
from backend.app.api.schemas import LLMHealth, LLMHealthProbe
from backend.app.contracts.stream import StreamEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["llm"])


def _emit_probe_audit_appended(bus: EventBus | None, trace_id: str, curr_hash: str) -> None:
    """probe 事件广播至所有活跃的 probe-watch-* 消费者（fan-out）。

    P1-3 修复前：固定 "probe-watch" 单队列，多 SSE 连接竞争消费（每条事件
    只有一个连接能读到）。修复后：每连接独立 trace_id，此处遍历广播。
    EventBusQueueFull 静默跳过——慢消费者丢事件优于阻塞广播。
    """
    if bus is None:
        return
    event = StreamEvent(
        trace_id="probe-watch",
        type="audit_appended",
        ts=time.time(),
        data={
            "seq": 0,
            "curr_hash": curr_hash,
            "phase": "probe_failed",
            "trace_id": trace_id,
        },
    )
    from backend.app.api.event_bus import EventBusQueueFull

    for tid in bus.all_trace_ids():
        if tid.startswith("probe-watch"):
            try:
                bus.put(tid, event)
            except EventBusQueueFull:
                pass


@router.get(
    "/health",
    summary="LLM 健康检查（配置态；?probe=true 时真探端点连通性）",
)
async def llm_health(
    _user: str = Depends(verify_token),  # noqa: ARG001
    probe: bool = Query(default=False, description="true → 真探端点连通性（real 模式）"),
    audit: AuditSink = Depends(get_audit),
    bus: EventBus | None = Depends(get_bus),
) -> LLMHealthProbe | LLMHealth:
    """返回 LLM 配置态；?probe=true 时额外真探端点可达性。

    无 probe：返回 LLMHealth（6 字段，不发 httpx）。
    probe=true：返回 LLMHealthProbe（LLMHealth + probe_* 字段）。

    probe 失败/超时时：
    - 落 SqliteAuditSink（phase=probe_failed, trace_id=probe-{epoch_ms}）
    - emit SSE audit_appended 到 EventBus（前端可订阅 /api/llm/health/events）
    - 响应 audit_trace_id 字段暴露给调用方便于查详情
    """
    from backend.app.llm.real_client import RealLLMClient, load_real_llm_config_from_env

    cfg = load_real_llm_config_from_env()
    base = LLMHealth(
        provider=cfg.provider,
        model=cfg.model,
        base_url=cfg.base_url,
        api_key_configured=bool(cfg.api_key),
        rate_limit_per_minute=cfg.rate_limit_per_minute,
        token_cap=cfg.token_cap,
        status="ok",
    )

    if not probe:
        return base

    # probe=true 路径：注入 audit_sink 让 probe 失败时同步落审计 + emit SSE
    timeout_s = float(os.environ.get("KYLIN_LLM_PROBE_TIMEOUT", "3"))
    client = RealLLMClient(cfg)
    result = await client.probe(timeout_s=timeout_s, audit_sink=audit)

    # probe 失败/超时：emit SSE audit_appended 给前端订阅者
    audit_trace_id = result.get("audit_trace_id")
    if isinstance(audit_trace_id, str) and result["probe_status"] in ("failed", "timeout"):
        # 从审计库反查 curr_hash 同步 emit（SSE 推送字节级与审计落库对齐）
        try:
            conn = getattr(audit, "_conn", None)
            if conn is not None:
                row = conn.execute(
                    "SELECT curr_hash FROM audit_records "
                    "WHERE trace_id = ? AND phase = 'probe_failed'",
                    (audit_trace_id,),
                ).fetchone()
                if row is not None:
                    _emit_probe_audit_appended(bus, audit_trace_id, str(row["curr_hash"]))
        except Exception as exc:  # noqa: BLE001 S8：SSE 推送失败不杀 probe 响应
            logger.warning("probe audit_appended SSE emit failed (S8 兜底): %s", exc)

    return LLMHealthProbe(
        **base.model_dump(),
        probe_enabled=not client.is_fixture,
        probe_status=result["probe_status"],  # type: ignore[arg-type]
        probe_latency_ms=result["probe_latency_ms"],  # type: ignore[arg-type]
        probe_error=result["probe_error"],  # type: ignore[arg-type]
    )


@router.get(
    "/health/events",
    summary="probe 审计 SSE 流（订阅 probe_failed audit_appended 事件）",
    # H-4 起返回类型是 StreamingResponse | JSONResponse（超限 503），二者都不是
    # Pydantic 可推导类型，须显式关闭 response_model 推导（同 system.py::readiness）。
    response_model=None,
)
async def health_events(
    request: Request,
    _user: str = Depends(verify_token),  # noqa: ARG001
    bus: EventBus = Depends(get_bus),
) -> StreamingResponse | JSONResponse:
    """probe 审计 SSE 流：推送 probe 失败/超时引发的 audit_appended 事件。

    客户端（运维 dashboard / monitoring）订阅此 SSE 即可拿到实时 probe 失败流；
    与 /api/audit/traces/{trace_id} 联用：先在 SSE 收 trace_id → 拉详情。

    S8：与 /api/chat/{trace_id}/events 同样接 Request.is_disconnected 断连清理。
    """
    # 之七十五 H-4：连接数上限（口径与 routers/chat.py 的 SSE 端点一致）。
    # 缺这道闸时本端点可被无限开连接——每条连接都在 bus 里占一个消费者、
    # 长期持 uvicorn worker，是 DoS 面。与 chat.py 同为软上限（不涉鉴权/哈希链），
    # asyncio 单线程下 check→create 的竞态窗口可忽略，不引入 Lock。
    max_conn = int(os.environ.get("KYLIN_SSE_MAX_CONN", "100") or "100")
    if bus.active_count >= max_conn:
        return JSONResponse(
            status_code=503,
            content={"detail": "SSE connection limit reached", "active_count": bus.active_count},
        )
    # probe-watch 改 fan-out：每条 SSE 连接独立 trace_id + queue，
    # 彼此互不抢事件（旧的固定 "probe-watch" 所有连接共享一个 queue，
    # 每条事件只有一个消费者能读到，其他连接静默丢失）。
    # 广播由 _emit_probe_audit_appended 遍历 all_trace_ids("probe-watch-") 前缀实现。
    import uuid as _uuid

    trace_id = f"probe-watch-{_uuid.uuid4().hex[:8]}"
    bus.create(trace_id)

    async def _event_source() -> AsyncIterator[str]:
        try:
            async for chunk in sse_stream(bus, trace_id):
                if await request.is_disconnected():
                    break
                yield chunk
        finally:
            bus.remove(trace_id)  # 每连接独立 queue，断开时立即清理（无并发踢走问题）

    return StreamingResponse(
        _event_source(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
