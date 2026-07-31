"""D bug 修复守门补: /api/llm/health_events 显式调 bus.create(trace_id).

实证 bug: probe-watch SSE 端点之前漏 bus.create("probe-watch") →
前端 SettingsView 真 EventSource 订阅后立即 queue closed。
da8072a 已修; P1-3 fan-out 进一步改为每连接独立 trace_id（probe-watch-{uuid}）。
"""

from __future__ import annotations


def test_t1_probe_watch_sse_creates_bus_queue() -> None:
    """T1: 调 health_events() 后, bus 中应出现 probe-watch- 前缀队列（fan-out 每连接独立）。"""
    import asyncio

    from backend.app.api.event_bus import EventBus
    from backend.app.api.routers import llm as llm_mod

    bus = EventBus()
    assert not any(k.startswith("probe-watch") for k in bus._queues)

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
    # fan-out：每连接独立 trace_id（probe-watch-{uuid}），不再是固定 "probe-watch"
    assert any(
        k.startswith("probe-watch") for k in bus._queues
    ), f"T1: bus.create(trace_id) 漏调, queues={list(bus._queues.keys())}"


def test_t2_probe_watch_sse_per_conn_remove_on_disconnect() -> None:
    """T2: fan-out 后每连接独立 trace_id，连接断开时 bus.remove 应被调（清理独立 queue）。

    旧行为是 long-life channel 不调 remove；P1-3 fan-out 后每连接是独立 queue，
    连接断开必须 remove 避免无主 queue 永驻。
    """
    import asyncio
    from unittest import mock as _m

    from backend.app.api.event_bus import EventBus
    from backend.app.api.routers import llm as llm_mod

    bus = EventBus()
    bus_remove_calls: list[str] = []

    with _m.patch.object(bus, "remove", side_effect=lambda tid: bus_remove_calls.append(tid)):

        class _Req:
            _calls = 0

            async def is_disconnected(self) -> bool:
                self._calls += 1
                return self._calls > 2  # 第三次轮询断开

        async def _drive():
            resp = await llm_mod.health_events(
                request=_Req(),  # type: ignore[arg-type]
                _user="dev",
                bus=bus,
            )
            # 消费 body_iterator 直到断开触发 finally
            async for _ in resp.body_iterator:
                pass
            return resp

        asyncio.run(_drive())
    # fan-out：断开后 finally bus.remove(trace_id) 必须被调
    assert (
        len(bus_remove_calls) == 1
    ), f"T2: fan-out 下连接断开应调 bus.remove 1 次，实际 {bus_remove_calls}"
