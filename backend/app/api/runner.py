"""后台 run/resume 驱动器：orchestrator 后台任务的异常兜底 + 终态收尾。

★命门（增量2）：
- run/resume 内部若抛**未预期异常**（系统级故障），必须 emit 一条 error 事件 +
  bus.close(trace_id)，绝不让 SSE 永久挂起等不到终止哨兵。
- 终态(FINISHED/REJECTED) → mark_done + bus.close(关闭 SSE)。
- WAIT_APPROVAL → 保活（不关闭 SSE，不 mark_done），等 /api/approvals/resume 续跑。

注：orchestrator 已对 httpx 网络异常/gateway 拦截 emit error 并正常返回（不 raise），
本层的 try/except 是对**逃逸到任务边界的系统级异常**的最后兜底（双保险）。
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.state_machine import State, is_terminal
from backend.app.api.event_bus import EventBus
from backend.app.api.session_registry import SessionRegistry
from backend.app.contracts.stream import StreamEvent
from backend.app.llm.adapter import Message


def _emit_error(bus: EventBus, trace_id: str, phase: str, message: str) -> None:
    """投递一条 error 事件到总线（绕过 SSEEventSink，直接进队列）。"""
    bus.put(
        trace_id,
        StreamEvent(
            trace_id=trace_id,
            type="error",
            ts=time.time(),
            data={"message": message, "phase": phase},
        ),
    )


def _finalize(state: State, bus: EventBus, registry: SessionRegistry, trace_id: str) -> None:
    """终态收尾：FINISHED/REJECTED → mark_done + close；WAIT_APPROVAL → 保活。"""
    if is_terminal(state):
        registry.mark_done(trace_id)
        bus.close(trace_id)
    # WAIT_APPROVAL：保活等 resume，不关闭 SSE


async def drive_run(
    orchestrator: Orchestrator,
    messages: Sequence[Message],
    user_intent: str,
    *,
    bus: EventBus,
    registry: SessionRegistry,
    trace_id: str,
) -> None:
    """后台执行 orchestrator.run，兜底异常并收尾。

    P1-3 修复：mark_done + bus.close 必须在 finally 块执行，
    否则 _emit_error 本身抛 EventBusQueueFull 时 SSE 会永久挂死，
    且会话永远算 in-flight → cleanup_expired 无界增长。
    """
    try:
        state = await orchestrator.run(messages, user_intent)
    except Exception as exc:  # noqa: BLE001 系统级故障最后兜底，防 SSE 挂死
        try:
            _emit_error(bus, trace_id, orchestrator.state.value, str(exc))
        finally:
            registry.mark_done(trace_id)
            bus.close(trace_id)
        return
    _finalize(state, bus, registry, trace_id)


async def drive_resume(
    orchestrator: Orchestrator,
    approved: bool,
    *,
    bus: EventBus,
    registry: SessionRegistry,
    trace_id: str,
) -> None:
    """后台执行 orchestrator.resume，兜底异常并收尾。

    P1-3 修复：与 drive_run 同款 try/finally 保证收尾必执行。
    """
    try:
        state = await orchestrator.resume(approved)
    except Exception as exc:  # noqa: BLE001 系统级故障最后兜底，防 SSE 挂死
        try:
            _emit_error(bus, trace_id, orchestrator.state.value, str(exc))
        finally:
            registry.mark_done(trace_id)
            bus.close(trace_id)
        return
    _finalize(state, bus, registry, trace_id)
