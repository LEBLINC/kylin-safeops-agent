"""增量2：POST /api/chat + GET /api/chat/{trace_id}/events(SSE)。

POST /api/chat：建 trace_id → 装配 Orchestrator（fake LLM/audit + 全局 gateway/bus）
→ 注册进 SessionRegistry → 后台 asyncio.create_task 跑 run（异常兜底见 runner）
→ 立即返回 trace_id + stream_url。

L-H1 IDOR 修复：body.session_id 若传 → store.assert_owner 校验。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.ports import AuditSink
from backend.app.agent.rca import RCAEngine
from backend.app.api.app import (
    get_audit,
    get_bus,
    get_gateway,
    get_llm,
    get_rca,
    get_registry,
    get_session_store,
)
from backend.app.api.auth import Principal
from backend.app.api.deps import principal_for_idor, verify_token
from backend.app.api.event_bus import EventBus, SSEEventSink, sse_stream
from backend.app.api.runner import drive_run
from backend.app.api.schemas import ChatRequest, ChatResponse
from backend.app.api.session_registry import OrchestratorSession, SessionRegistry
from backend.app.api.session_store import SessionStore
from backend.app.llm.adapter import LLMAdapter
from backend.app.mcp.gateway import MCPGateway

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def post_chat(
    body: ChatRequest,
    principal: Principal = Depends(principal_for_idor),
    bus: EventBus = Depends(get_bus),
    registry: SessionRegistry = Depends(get_registry),
    gateway: MCPGateway = Depends(get_gateway),
    llm: LLMAdapter = Depends(get_llm),
    audit: AuditSink = Depends(get_audit),
    rca: RCAEngine = Depends(get_rca),
    store: SessionStore = Depends(get_session_store),
) -> ChatResponse:
    """建会话请求：装配 orchestrator，后台跑 run，立即返回 trace_id。

    L-H1：body.session_id 若传 → assert_owner 校验（owner or admin 才能续 chat）。
    """
    trace_id = uuid.uuid4().hex
    bus.create(trace_id)

    orchestrator = Orchestrator(
        llm=llm,
        gateway=gateway,
        audit=audit,
        events=SSEEventSink(bus, trace_id),
        rca=rca,
        trace_id=trace_id,
    )
    session = OrchestratorSession(trace_id=trace_id, orchestrator=orchestrator)
    registry.register(session)

    # L-M3：审计 actor 溯源（用 principal_for_idor 派生的 Principal）
    orchestrator.set_actor(principal.user, principal.roles)

    # L-H1：body.session_id 走 assert_owner
    if body.session_id is not None:
        store.assert_owner(body.session_id, principal.user, is_admin="admin" in principal.roles)

    messages = [{"role": "user", "content": body.message}]
    session.task = asyncio.create_task(
        drive_run(
            orchestrator,
            messages,
            body.message,
            bus=bus,
            registry=registry,
            trace_id=trace_id,
        )
    )

    return ChatResponse(
        session_id=body.session_id,
        trace_id=trace_id,
        stream_url=f"/api/chat/{trace_id}/events",
    )


@router.get("/{trace_id}/events")
async def get_events(
    trace_id: str,
    request: Request,
    _user: str = Depends(verify_token),
    bus: EventBus = Depends(get_bus),
) -> StreamingResponse:
    """SSE 事件流：消费 trace_id 队列推前端，检测断连即清理队列。"""

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
