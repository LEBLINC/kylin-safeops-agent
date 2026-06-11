"""增量2：POST /api/chat + GET /api/chat/{trace_id}/events(SSE)。

POST /api/chat：建 trace_id → 装配 Orchestrator（fake LLM/audit + 全局 gateway/bus）
→ 注册进 SessionRegistry → 后台 asyncio.create_task 跑 run（异常兜底见 runner）
→ 立即返回 trace_id + stream_url。

GET .../events：StreamingResponse 推 SSE；落实增量1 TODO——接 Request.is_disconnected
检测客户端断连，断连即跳出并 bus.remove(trace_id) 防队列无界堆积。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.ports import AuditSink
from backend.app.api.app import (
    get_audit,
    get_bus,
    get_gateway,
    get_llm,
    get_registry,
    get_session_store,
)
from backend.app.api.deps import verify_token
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
    _user: str = Depends(verify_token),
    bus: EventBus = Depends(get_bus),
    registry: SessionRegistry = Depends(get_registry),
    gateway: MCPGateway = Depends(get_gateway),
    llm: LLMAdapter = Depends(get_llm),
    audit: AuditSink = Depends(get_audit),
    store: SessionStore = Depends(get_session_store),
) -> ChatResponse:
    """建会话请求：装配 orchestrator，后台跑 run，立即返回 trace_id。"""
    trace_id = uuid.uuid4().hex
    bus.create(trace_id)

    orchestrator = Orchestrator(
        llm=llm,
        gateway=gateway,
        audit=audit,
        events=SSEEventSink(bus, trace_id),
        trace_id=trace_id,
    )
    session = OrchestratorSession(trace_id=trace_id, orchestrator=orchestrator)
    registry.register(session)

    # 触达对话会话（更新 updated_at），不存在则忽略（前端可能用本地 session_id）
    if body.session_id is not None:
        store.touch(body.session_id)

    messages = [{"role": "user", "content": body.message}]
    # 后台任务：run 被 runner 兜异常（系统级故障 → emit error + close，防 SSE 挂死）。
    # task 存进 session.task 防 GC 提前回收。
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
                # 落实增量1 TODO：客户端断连即跳出（每条事件/心跳后有检测机会）
                if await request.is_disconnected():
                    break
                yield chunk
        finally:
            # 断连或正常结束（done 哨兵）后移除队列，防无界堆积
            bus.remove(trace_id)

    return StreamingResponse(
        _event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
