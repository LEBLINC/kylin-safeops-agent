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


# ---- 之七十五 H-4: /api/llm/health/events 同样接连接数上限 -------------------


def test_h4_llm_health_events_limit_returns_503(monkeypatch) -> None:
    """H-4: probe-watch SSE 达上限 → 503，且不为 probe-watch 建队列。

    该端点此前无连接数上限——可被无限开连接，每条都在 bus 占消费者 + 长期持
    uvicorn worker，是 DoS 面（chat.py 的同类端点早有此闸，本端点漏了）。
    """
    from backend.app.api.routers import llm as llm_mod

    monkeypatch.setenv("KYLIN_SSE_MAX_CONN", "2")
    bus = EventBus()
    bus.create("existing-1")
    bus.create("existing-2")

    async def _run():
        return await llm_mod.health_events(request=_Req(), _user="dev", bus=bus)

    resp = asyncio.run(_run())
    assert resp.status_code == 503, f"H-4 期望 503, got {resp.status_code}"
    assert "probe-watch" not in bus._queues, "H-4: 达上限不应建 probe-watch 队列"


def test_h4_llm_health_events_ok_below_limit(monkeypatch) -> None:
    """H-4: 未达上限 → 正常受理（非 503），probe-watch 队列建立。

    不消费 body_iterator：probe-watch 是 long-life channel，其 sse_stream 会等到
    _HEARTBEAT_INTERVAL（15s）才吐第一个 keepalive——耗尽它会让本用例白等 15 秒。
    这里只验"受理与否 + 队列是否建立"，流式内容由 test_probe_watch_sse.py 覆盖。
    """
    from backend.app.api.routers import llm as llm_mod

    monkeypatch.setenv("KYLIN_SSE_MAX_CONN", "5")
    bus = EventBus()

    async def _run():
        return await llm_mod.health_events(request=_Req(), _user="dev", bus=bus)

    resp = asyncio.run(_run())
    assert resp.status_code != 503, f"H-4 未达上限应受理, got {resp.status_code}"
    assert "probe-watch" in bus._queues, "H-4: 未达上限应建立 probe-watch 队列"


def test_h4_same_env_var_as_chat_endpoint() -> None:
    """H-4: 与 chat.py 的 SSE 端点共用同一 env（KYLIN_SSE_MAX_CONN），口径不分叉。"""
    import inspect

    from backend.app.api.routers import chat as chat_mod
    from backend.app.api.routers import llm as llm_mod

    chat_src = inspect.getsource(chat_mod.get_events)
    llm_src = inspect.getsource(llm_mod.health_events)
    for src, who in ((chat_src, "chat"), (llm_src, "llm")):
        assert 'KYLIN_SSE_MAX_CONN", "100"' in src, f"H-4: {who} 端点应读同一 env 同一默认值"
        assert "bus.active_count >=" in src, f"H-4: {who} 端点应比对 active_count"
