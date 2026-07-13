"""B4 P2 SSE QueueFull 兜底。"""

from __future__ import annotations

import asyncio
from unittest import mock

from backend.app.api.event_bus import EventBus, EventBusQueueFull
from backend.app.api.routers import chat as chat_mod


class _Req:
    async def is_disconnected(self):
        return False


async def _drive_get_events(bus, trace_id, raise_queue_full=True):
    """Drive chat.get_events with mocked sse_stream that raises EventBusQueueFull."""

    async def _fake_sse(_b, _t):
        if raise_queue_full:
            raise EventBusQueueFull("forced for test")
        yield ""

    with mock.patch.object(chat_mod, "sse_stream", _fake_sse):
        resp = await chat_mod.get_events(
            trace_id=trace_id,
            request=_Req(),
            _user="dev",
            bus=bus,
        )
        # Starlette StreamingResponse: body_iterator is set in __init__
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
        return "".join(chunks)


# ---- T1 ----


def test_t1_sse_yields_queue_full_error_event() -> None:
    """T1: SSE 端点当 sse_stream 抛 EventBusQueueFull → yield queue_full error event + bus.remove。"""
    bus = EventBus()
    trace_id = "trace-q1"

    body = asyncio.run(_drive_get_events(bus, trace_id, raise_queue_full=True))

    assert "event: error" in body, f"T1 期望 SSE error 事件, got body={body!r}"
    assert '"cause":"queue_full"' in body
    assert trace_id in body
    assert trace_id not in bus._queues, f"T1: bus.remove({trace_id}) 未调"


# ---- T2 ----


def test_t2_sse_queue_full_calls_bus_remove() -> None:
    """T2: spy bus.remove 总被调（无论 queue_full raise 路径）— 与 T1 共享证据不重复写。"""
    bus = EventBus()
    trace_id = "trace-q2"
    asyncio.run(_drive_get_events(bus, trace_id, raise_queue_full=True))
    assert (
        trace_id not in bus._queues
    ), f"T2: bus.remove({trace_id}) 未调, _queues={list(bus._queues.keys())}"
