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
from fastapi.responses import StreamingResponse

from backend.app.agent.ports import AuditSink, EventSink
from backend.app.api.app import get_audit, get_bus
from backend.app.api.deps import verify_token
from backend.app.api.event_bus import EventBus, SSEEventSink, sse_stream
from backend.app.api.schemas import LLMHealth, LLMHealthProbe
from backend.app.contracts.stream import StreamEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["llm"])


def _emit_probe_audit_appended(bus: EventBus | None, trace_id: str, curr_hash: str) -> None:
    """同步 emit audit_appended 事件到 EventBus 固定 channel（前端 SSE 订阅可见）。

    路由设计：probe 失败时 SSE 推到固定 channel "probe-watch"（聚合所有 probe 事件），
    与 /api/audit/traces/{trace_id} 一一对应——客户端 SSE 收到 trace_id 后再拉详情。
    原始 trace_id 写进 StreamEvent.data['trace_id'] 字段透传给前端。
    """
    if bus is None:
        return
    sink: EventSink = SSEEventSink(bus, "probe-watch")
    sink.emit(
        StreamEvent(
            trace_id="probe-watch",
            type="audit_appended",
            ts=time.time(),
            data={
                "seq": 0,
                "curr_hash": curr_hash,
                "phase": "probe_failed",
                "trace_id": trace_id,  # 真实 trace_id（用于查 audit/traces/{id}）
            },
        )
    )


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
)
async def health_events(
    request: Request,
    _user: str = Depends(verify_token),  # noqa: ARG001
    bus: EventBus = Depends(get_bus),
) -> StreamingResponse:
    """probe 审计 SSE 流：推送 probe 失败/超时引发的 audit_appended 事件。

    客户端（X 的运维 dashboard / monitoring）订阅此 SSE 即可拿到实时 probe 失败流；
    与 /api/audit/traces/{trace_id} 联用：先在 SSE 收 trace_id → 拉详情。

    S8：与 /api/chat/{trace_id}/events 同样接 Request.is_disconnected 断连清理。
    """
    # probe 事件统一 trace_id 前缀，方便客户端订阅过滤
    # 但当前 SSEEventSink(bus, trace_id) 是单 trace 单队列，运维 dashboard 要收所有
    # probe 事件，需要新建一个聚合队列。简化：用固定 trace_id "probe-watch" 作 channel。
    trace_id = "probe-watch"

    async def _event_source() -> AsyncIterator[str]:
        try:
            async for chunk in sse_stream(bus, trace_id):
                if await request.is_disconnected():
                    break
                yield chunk
        finally:
            bus.remove(trace_id)

    return StreamingResponse(
        _event_source(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
