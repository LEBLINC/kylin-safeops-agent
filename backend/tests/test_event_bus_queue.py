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


def test_h2_default_maxsize_is_bounded(monkeypatch) -> None:
    """H-2: 不设 env 时队列必须有界（此前默认 "0" = 无界，L-H14 形同未生效）。

    未设 env 的部署占多数，默认无界意味着慢消费者/断连未清理的 SSE 会让事件在
    内存里无限堆积直到 OOM。本断言锁死"默认即保护"。
    """
    monkeypatch.delenv("KYLIN_SSE_QUEUE_MAX", raising=False)
    bus = EventBus()
    queue = bus.create("h2-default")
    assert queue.maxsize > 0, "H-2: 默认必须有界"
    assert queue.maxsize == EventBus.DEFAULT_MAXSIZE == 512


def test_h2_env_overrides_default(monkeypatch) -> None:
    """H-2: env 显式设值仍优先于默认（运维可调）。"""
    monkeypatch.setenv("KYLIN_SSE_QUEUE_MAX", "7")
    queue = EventBus().create("h2-env")
    assert queue.maxsize == 7


def test_h2_explicit_zero_still_unbounded(monkeypatch) -> None:
    """H-2: 显式传 0 保留"无界"语义——只是不再是默认值。"""
    monkeypatch.delenv("KYLIN_SSE_QUEUE_MAX", raising=False)
    queue = EventBus(maxsize=0).create("h2-zero")
    assert queue.maxsize == 0


def test_h2_service_unit_declares_queue_max() -> None:
    """H-2: app systemd 单元显式声明 KYLIN_SSE_QUEUE_MAX（与代码默认双保险）。"""
    import pathlib

    unit = (
        pathlib.Path(__file__).resolve().parents[2]
        / "deploy"
        / "app"
        / "kylin-safeops-agent.service"
    )
    text = unit.read_text(encoding="utf-8")
    assert "KYLIN_SSE_QUEUE_MAX=512" in text, "H-2: 单元应显式声明队列上限（便于运维审查）"
