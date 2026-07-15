"""C2（阶段6 第二梯队）：SSE 并发连接上限守门测试。

覆盖 2 用例：
  T1 达 KYLIN_SSE_MAX_CONN 上限 → 新连接 503
  T2 释放（bus.remove）后 → 可再连（200）
"""

from __future__ import annotations

import asyncio

from backend.app.api.event_bus import EventBus
from backend.app.api.routers import chat as chat_mod


class _Req:
    async def is_disconnected(self):
        return True  # 立即断连，驱动 generator 尽快退出


def test_t1_sse_connection_limit_returns_503(monkeypatch) -> None:
    """T1: bus.active_count 已达上限 → get_events 直接 503，不建新队列。"""
    monkeypatch.setenv("KYLIN_SSE_MAX_CONN", "2")
    bus = EventBus()
    bus.create("existing-1")
    bus.create("existing-2")

    async def _run():
        return await chat_mod.get_events(
            trace_id="new-trace",
            request=_Req(),
            _user="dev",
            bus=bus,
        )

    resp = asyncio.run(_run())
    assert resp.status_code == 503, f"T1 期望 503, got {resp.status_code}"
    assert "new-trace" not in bus._queues, "T1: 达上限不应为新 trace 建队列"


def test_t2_sse_connection_available_after_release(monkeypatch) -> None:
    """T2: 达上限后释放一个连接（bus.remove）→ active_count 降，新连接可通过（非 503）。"""
    monkeypatch.setenv("KYLIN_SSE_MAX_CONN", "1")
    bus = EventBus()
    bus.create("existing-1")
    assert bus.active_count == 1

    bus.remove("existing-1")
    assert bus.active_count == 0

    async def _run():
        resp = await chat_mod.get_events(
            trace_id="new-trace-2",
            request=_Req(),
            _user="dev",
            bus=bus,
        )
        # 消费一次 body_iterator 触发 finally: bus.remove（避免遗留队列影响后续用例）
        async for _ in resp.body_iterator:
            pass
        return resp

    resp = asyncio.run(_run())
    assert resp.status_code != 503, f"T2 期望非 503（连接应被受理）, got {resp.status_code}"
