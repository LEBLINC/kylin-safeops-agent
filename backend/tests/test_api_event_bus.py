"""增量1 冒烟：EventBus + SSEEventSink + SessionRegistry 空链路跑通。

验证审批期保持连接 + resume 续推的底座：
- SSEEventSink.emit 把 orchestrator 事件投递到正确 trace_id 队列。
- sse_stream 消费队列、终止哨兵正常关闭、心跳超时不丢事件。
- SessionRegistry 保持实例存活 + 终态清理。

不触网、不跑真命令；fake 注入协作者依赖。
"""

from __future__ import annotations

import asyncio
import json

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.state_machine import State
from backend.app.api.event_bus import EventBus, SSEEventSink, sse_stream
from backend.app.api.session_registry import OrchestratorSession, SessionRegistry
from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.stream import StreamEvent
from backend.app.contracts.untrusted import ToolResult
from backend.app.llm.adapter import LLMAdapter
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry


# ---- fake 协作者依赖 -----------------------------------------------------


class _AllowPolicy:
    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return PolicyVerdict(
            decision="allow",
            final_risk="R0",
            matched_rules=[],
            reason="fake allow",
            approval_required=False,
        )


class _FakeExecutor:
    async def execute(self, tool: CandidateTool) -> ToolResult:
        return ToolResult(tool=tool.name, args=tool.args, exit_code=0, stdout_truncated="ok")


class _Audit:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


def _seq_llm(*outputs: str) -> LLMAdapter:
    seq = list(outputs)
    calls = {"n": 0}

    async def fn(messages):  # noqa: ANN001
        out = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return out

    return LLMAdapter(completion_fn=fn)


# ---- EventBus + SSEEventSink ---------------------------------------------


def test_event_bus_routes_to_correct_trace() -> None:
    """emit 的事件按 trace_id 路由到对应队列，互不串扰。"""
    bus = EventBus()
    bus.create("trace-a")
    bus.create("trace-b")
    sink_a = SSEEventSink(bus, "trace-a")
    sink_b = SSEEventSink(bus, "trace-b")

    sink_a.emit(StreamEvent(trace_id="trace-a", type="verified", ts=1.0, data={"summary": "a"}))
    sink_b.emit(StreamEvent(trace_id="trace-b", type="verified", ts=2.0, data={"summary": "b"}))

    qa = bus.get("trace-a")
    qb = bus.get("trace-b")
    assert qa is not None and qb is not None
    assert qa.qsize() == 1
    assert qb.qsize() == 1


def test_event_bus_put_unknown_trace_silently_dropped() -> None:
    """向未创建的 trace_id 投递不报错（防竞态：SSE 尚未连上时）。"""
    bus = EventBus()
    bus.put("ghost", StreamEvent(trace_id="ghost", type="verified", ts=1.0, data={}))
    assert bus.get("ghost") is None


def test_sse_stream_yields_events_then_done() -> None:
    """sse_stream 消费事件并以 done 哨兵正常结束。"""
    bus = EventBus()
    bus.create("t1")
    bus.put("t1", StreamEvent(trace_id="t1", type="intent_parsed", ts=1.0, data={"x": 1}))
    bus.close("t1")

    async def drain() -> list[str]:
        return [chunk async for chunk in sse_stream(bus, "t1")]

    chunks = asyncio.run(drain())
    # 第一条是事件，最后一条是 done
    assert chunks[0].startswith("data: ")
    payload = json.loads(chunks[0][len("data: ") :].strip())
    assert payload["type"] == "intent_parsed"
    assert chunks[-1] == "event: done\ndata: {}\n\n"


def test_sse_stream_unknown_trace_returns_empty() -> None:
    """未知 trace_id 的 SSE 流立即结束（无队列）。"""

    async def drain() -> list[str]:
        return [chunk async for chunk in sse_stream(EventBus(), "missing")]

    assert asyncio.run(drain()) == []


# ---- SessionRegistry ------------------------------------------------------


def _build_session(trace_id: str) -> OrchestratorSession:
    registry = ToolRegistry()
    gateway = MCPGateway(registry, _AllowPolicy(), _FakeExecutor())  # type: ignore[arg-type]
    bus = EventBus()
    bus.create(trace_id)
    orch = Orchestrator(
        llm=_seq_llm("{}"),
        gateway=gateway,
        audit=_Audit(),
        events=SSEEventSink(bus, trace_id),
        trace_id=trace_id,
    )
    return OrchestratorSession(trace_id=trace_id, orchestrator=orch)


def test_session_registry_keeps_instance_alive() -> None:
    """注册后按 trace_id 取回同一实例（resume 续跑前提）。"""
    reg = SessionRegistry()
    session = _build_session("keep-1")
    reg.register(session)
    got = reg.get("keep-1")
    assert got is session
    assert got.orchestrator.trace_id == "keep-1"


def test_session_registry_cleanup_only_expired_done() -> None:
    """清理只移除已终止且超期的会话；未完成的保留。"""
    reg = SessionRegistry()
    live = _build_session("live")
    reg.register(live)
    # 未标记 finished → 不清理
    assert reg.cleanup_expired() == []
    assert reg.total_count == 1


def test_cleanup_removes_session_and_queue_together() -> None:
    """修订1：session 与 queue 同生命周期——cleanup 后两者皆消失，防 queue 泄漏。

    模拟 app._periodic_cleanup 的逻辑：cleanup_expired 返回被清理 tid，逐个 bus.remove。
    """
    import time

    from backend.app.api import session_registry as sr

    reg = SessionRegistry()
    bus = EventBus()
    tid = "expire-1"
    bus.create(tid)
    session = _build_session(tid)
    reg.register(session)

    # 标记 finished 且 mock 超期（finished_at 拨到远古）
    reg.mark_done(tid)
    got = reg.get(tid)
    assert got is not None
    got.finished_at = time.time() - sr._RETENTION_SECONDS - 1

    removed = reg.cleanup_expired()
    assert removed == [tid]
    # 调用方据返回列表移除队列
    for t in removed:
        bus.remove(t)

    assert reg.get(tid) is None
    assert bus.get(tid) is None


# ---- 端到端：emit 经 SSEEventSink 流到 SSE 消费端 -------------------------


def test_orchestrator_events_flow_through_sse_sink() -> None:
    """orchestrator 全程 emit 经 SSEEventSink 进总线，sse_stream 能消费到关键事件。"""
    bus = EventBus()
    trace_id = "flow-1"
    bus.create(trace_id)

    registry = ToolRegistry()
    gateway = MCPGateway(registry, _AllowPolicy(), _FakeExecutor())  # type: ignore[arg-type]
    # 无候选工具的简单意图 → 走到 REJECTED（无工具可执行），仍产出事件链
    intent = json.dumps(
        {
            "intent": "noop",
            "confidence": 0.9,
            "need_observation": False,
            "candidate_tools": [],
            "risk_hint": "low",
            "justification": "nothing to do",
        }
    )
    orch = Orchestrator(
        llm=_seq_llm(intent),
        gateway=gateway,
        audit=_Audit(),
        events=SSEEventSink(bus, trace_id),
        trace_id=trace_id,
    )

    async def run_and_drain() -> tuple[State, list[str]]:
        state = await orch.run([{"role": "user", "content": "hi"}])
        bus.close(trace_id)  # 终态后关闭 SSE
        chunks = [chunk async for chunk in sse_stream(bus, trace_id)]
        return state, chunks

    state, chunks = asyncio.run(run_and_drain())
    assert state is State.REJECTED  # 无候选 → 合成 deny
    body = "".join(chunks)
    assert "intent_parsed" in body
    assert "policy_verdict" in body
    assert chunks[-1] == "event: done\ndata: {}\n\n"
