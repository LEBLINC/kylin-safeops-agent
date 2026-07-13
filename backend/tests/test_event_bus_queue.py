"""B4 commit 1 守门测试: EventBus Queue maxsize + EventBusQueueFull fallback。

覆盖 2 用例:
  T1 test_event_bus_queue_full_returns_exception: monkeypatch maxsize=1, put 2 次 → 第 2 次 raise EventBusQueueFull
  T2 test_event_bus_active_count_with_maxsize: verify active_count() <= maxsize + 1
"""

from __future__ import annotations

from backend.app.api.event_bus import EventBus, EventBusQueueFull

# ---- T1: maxsize=1 + put 2 次 → EventBusQueueFull ----


def test_t1_event_bus_queue_full_returns_exception() -> None:
    """T1: EventBus(maxsize=1) 第 2 次 put_nowait 触发 asyncio.QueueFull → 转 EventBusQueueFull。"""
    bus = EventBus(maxsize=1)
    bus.create("trace-001")

    bus.put("trace-001", {"event": "first"})
    with pytest.raises(EventBusQueueFull):
        bus.put("trace-001", {"event": "second"})


# ---- T2: active_count <= maxsize + 1 (实际约束 maxsize 内) ----


def test_t2_event_bus_active_count_with_maxsize() -> None:
    """T2: 多个 trace_id 创建的队列总数 active_count() 反映."""
    bus = EventBus(maxsize=2)
    bus.create("t1")
    bus.create("t2")
    bus.create("t3")
    assert bus.active_count == 3
    # active_count 与 maxsize 无关 (active_count = 创建的 trace 数)
    # maxsize 限制的是单个队列的事件数,不是队列数


# 延迟 import
import pytest
