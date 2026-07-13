"""B4 commit 1 守门测试: EventBus Queue maxsize + EventBusQueueFull fallback。

覆盖 2 用例:
  T1: maxsize=1 + put 2 次 → EventBusQueueFull
  T2: 多个 trace_id 创建的队列总数 active_count()
"""

from __future__ import annotations

import pytest

from backend.app.api.event_bus import EventBus, EventBusQueueFull

# ---- T1 ----


def test_t1_event_bus_queue_full_returns_exception() -> None:
    """T1: EventBus(maxsize=1) 第 2 次 put_nowait 触发 QueueFull → EventBusQueueFull。"""
    bus = EventBus(maxsize=1)
    bus.create("trace-001")

    bus.put("trace-001", {"event": "first"})
    with pytest.raises(EventBusQueueFull):
        bus.put("trace-001", {"event": "second"})


# ---- T2 ----


def test_t2_event_bus_active_count_with_maxsize() -> None:
    """T2: 多个 trace_id 创建的队列总数 active_count() 反映."""
    bus = EventBus(maxsize=2)
    bus.create("t1")
    bus.create("t2")
    bus.create("t3")
    assert bus.active_count == 3
