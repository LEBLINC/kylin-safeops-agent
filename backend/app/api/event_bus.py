"""按 trace_id 分发的内存事件总线 + SSE EventSink 实现。

设计要点（审批期保持连接 + resume 续推）：
- 每个 trace_id 对应一个 asyncio.Queue[StreamEvent | None]，None 为终止哨兵。
- SSEEventSink 实现 contracts/stream.EventSink Protocol：emit() 把事件投入 queue。
- SSE 端点的 async generator 循环 await queue.get()：
    - 审批等待期 queue 为空 → 阻塞 → HTTP 连接 keep-alive。
    - resume 后 orchestrator 继续 emit → 同一 queue → generator 被唤醒继续推。
    - None 到达 → generator return → StreamingResponse 正常结束。
- 心跳：定时注入 SSE 注释行 `:keepalive\\n\\n`，防代理/浏览器超时断开。

安全：本层无特权操作，仅转发结构化事件；事件内容已由 orchestrator 层保证安全。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator

from backend.app.agent.metrics import get_metrics
from backend.app.contracts.stream import StreamEvent

logger = logging.getLogger(__name__)

# SSE 心跳间隔（秒）：无事件时发 SSE 注释行防代理断连
_HEARTBEAT_INTERVAL: float = 15.0


class EventBusQueueFull(RuntimeError):
    """L-H14: SSE 事件队列已满（QueueFull）→ raise EventBusQueueFull。

    调用方（chat.get_events / SSEEventSink）应 try/except 兜底：emit error event
    或 drain queue 防止事件无限堆积。
    """


class EventBus:
    """按 trace_id 分发的内存事件总线。

    线程安全由 asyncio 事件循环保证（单线程协程模型）；
    不跨进程——单实例部署（麒麟靶机单节点，满足当前需求）。

    L-H14: __init__ 接受 maxsize（int），默认 None = 不限（向后兼容）。
    显式传 maxsize=int 时创建 asyncio.Queue(maxsize=...)；put_nowait 满则 raise EventBusQueueFull。
    """

    def __init__(self, maxsize: int | None = None) -> None:
        """L-H14: maxsize=None 不限；显式传 int 走 QueueFull 路径。

        生产默认由 lifespan 读 env KYLIN_SSE_QUEUE_MAX 注入；单元测试可显式传。
        """
        if maxsize is None:
            maxsize = int(os.environ.get("KYLIN_SSE_QUEUE_MAX", "0") or "0")
        self._maxsize = maxsize
        self._queues: dict[str, asyncio.Queue[StreamEvent | None]] = {}

    def create(self, trace_id: str) -> asyncio.Queue[StreamEvent | None]:
        """为 trace_id 创建事件队列。重复创建则复用已有队列。"""
        if trace_id not in self._queues:
            self._queues[trace_id] = asyncio.Queue(maxsize=self._maxsize or 0)
        # C1：SSE 活跃连接数埋点（gauge，与 active_count 同口径）
        get_metrics().set_gauge("sse.active_count", len(self._queues))
        return self._queues[trace_id]

    def get(self, trace_id: str) -> asyncio.Queue[StreamEvent | None] | None:
        """获取 trace_id 对应的队列，不存在返回 None。"""
        return self._queues.get(trace_id)

    def put(self, trace_id: str, event: StreamEvent) -> None:
        """向 trace_id 的队列投递事件。队列不存在则静默丢弃（防竞态）。

        队列满 → raise EventBusQueueFull（L-H14）由调用方决定兜底（emit error SSE）。
        """
        queue = self._queues.get(trace_id)
        if queue is None:
            return
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull as exc:
            raise EventBusQueueFull(
                f"event queue full for trace_id={trace_id} (maxsize={self._maxsize})"
            ) from exc

    def close(self, trace_id: str) -> None:
        """向 trace_id 投递终止哨兵（None），通知 SSE 端正常结束。"""
        queue = self._queues.get(trace_id)
        if queue is not None:
            queue.put_nowait(None)

    def remove(self, trace_id: str) -> None:
        """移除 trace_id 队列（清理资源）。"""
        self._queues.pop(trace_id, None)
        get_metrics().set_gauge("sse.active_count", len(self._queues))

    def drain_all(self) -> int:
        """L-B4-2：lifespan shutdown 阶段移除所有队列，返回移除数。

        幂等：已 done / 已 None 的队列也算移除（不重不漏）。
        注：本方法**不**消费 queue 中的事件——SSE 端点关闭事件流即可（前端连接已断）。
        """
        keys = list(self._queues.keys())
        for key in keys:
            self._queues.pop(key, None)
        get_metrics().set_gauge("sse.active_count", len(self._queues))
        return len(keys)

    @property
    def active_count(self) -> int:
        """当前存活队列数（监控用）。"""
        return len(self._queues)


class SSEEventSink:
    """实现 EventSink Protocol：emit() 把 StreamEvent 投入对应 trace_id 的队列。

    由 Orchestrator 持有；每个 Orchestrator 实例绑定一个 trace_id，
    通过 EventBus 路由到正确的 SSE 消费端。
    """

    def __init__(self, bus: EventBus, trace_id: str) -> None:
        self._bus = bus
        self._trace_id = trace_id

    def emit(self, event: StreamEvent) -> None:
        """实现 EventSink.emit：投递到总线。"""
        self._bus.put(self._trace_id, event)


async def sse_stream(bus: EventBus, trace_id: str) -> AsyncIterator[str]:
    """SSE async generator：消费 queue 并 yield SSE 格式文本。

    - 正常事件 → `data: {json}\\n\\n`
    - 心跳 → `: keepalive\\n\\n`（SSE 注释行，客户端忽略）
    - None 哨兵 → yield `event: done\\ndata: {}\\n\\n` 后 return

    TODO(增量2): 接 FastAPI Request.is_disconnected 检测客户端断连，
        断连即 bus.remove 防队列无界堆积。
    已知限制:
        - 当前无 Last-Event-ID 事件回放，SSE 断线重连不能续传中间事件。
        - 单消费者约束：同一 trace 若开多条 SSE 会瓜分事件（queue.get 互斥消费）。
        重连续传方案待 L 决策（X 的 Q-X3 需求）。
    """
    queue = bus.get(trace_id)
    if queue is None:
        return

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL)
        except asyncio.TimeoutError:
            # 心跳：防代理/浏览器超时断开
            yield ": keepalive\n\n"
            continue

        if event is None:
            # 终止哨兵：通知前端流结束
            yield "event: done\ndata: {}\n\n"
            return

        # 正常事件
        yield f"data: {event.model_dump_json()}\n\n"
