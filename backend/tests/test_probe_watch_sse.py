"""D bug 修复守门补: /api/llm/health_events 显式调 bus.create(trace_id).

实证 bug: probe-watch SSE 端点之前漏 bus.create("probe-watch") →
前端 SettingsView 真 EventSource 订阅后立即 queue closed。
da8072a 已修;本文件显式守门此行为。
"""

from __future__ import annotations


def test_t1_probe_watch_sse_creates_bus_queue() -> None:
    """T1: 调 health_events() 后,bus 中应出现 trace_id='probe-watch' queue (D bug 修复守门)."""
    import asyncio

    from backend.app.api.event_bus import EventBus
    from backend.app.api.routers import llm as llm_mod

    bus = EventBus()
    # ensure bus does NOT have probe-watch yet
    assert "probe-watch" not in bus._queues

    class _Req:
        async def is_disconnected(self) -> bool:
            return False

    async def _drive():
        resp = await llm_mod.health_events(
            request=_Req(),
            _user="dev",
            bus=bus,
        )
        return resp

    asyncio.run(_drive())
    # Stop iteration, queue should now exist
    assert (
        "probe-watch" in bus._queues
    ), f"T1: D bug 未修 — bus.create('probe-watch') 漏调, queues={list(bus._queues.keys())}"


def test_t2_probe_watch_sse_long_life_no_remove() -> None:
    """T2: 守门 'probe-watch' 是 long-life channel — bus.remove 不应在 finally 调."""
    import asyncio
    from unittest import mock as _m

    from backend.app.api.event_bus import EventBus
    from backend.app.api.routers import llm as llm_mod

    bus = EventBus()
    bus_remove_calls: list[str] = []

    with _m.patch.object(bus, "remove", side_effect=lambda tid: bus_remove_calls.append(tid)):

        class _Req:
            async def is_disconnected(self) -> bool:
                return False

        async def _drive():
            resp = await llm_mod.health_events(
                request=_Req(),  # type: ignore[arg-type]
                _user="dev",
                bus=bus,
            )
            # 立即断开 (StopAsyncIteration)
            return resp

        asyncio.run(_drive())
        # 没有 disconnect → SSE 流还在跑; bus.remove 不应被调
        # (probe-watch 是 long-life channel, finally 故意不动)
    assert bus_remove_calls == [], "T2: probe-watch 是 long-life channel,b... bus_remove_calls"
