"""任务甲 — B2 RCA 接线验证（NullRCA → DefaultRCAEngine 端到端）。

覆盖三层接线：
1. 独立 RCA 端点（POST /api/rca/analyze + GET /api/rca/{trace_id}）经真
   DefaultRCAEngine 产**非空**报告（含 DefaultRCAEngine 输出键）。
2. 主链路注入：POST /api/chat 构造的 Orchestrator 注入的是真 DefaultRCAEngine
   （engine 类型断言，不强造 rca 事件——FakeExecutor 罐头证据可能不触发）。
3. get_rca provider 返回 DefaultRCAEngine；并直接驱动一条会产非空报告的证据，
   断言 orchestrator emit 了契约6 "rca" 事件（证明调起点真实连通）。

红线自检：RCA 报告是展示数据；orchestrator 不执行其内容（report 仅经 emit 推前端）。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.state_machine import State
from backend.app.api import app as app_module
from backend.app.api.app import create_app, get_rca, lifespan
from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.stream import StreamEvent
from backend.app.contracts.untrusted import ToolResult
from backend.app.llm.adapter import LLMAdapter
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from mcp_servers.rca import DefaultRCAEngine

# DefaultRCAEngine 报告的稳定输出键（_finalize_report 保证均存在）。
_RCA_REPORT_KEYS = (
    "problem_type",
    "summary",
    "root_cause_candidates",
    "recommended_next_steps",
    "dangerous_actions_rejected",
)


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ---- 1. 独立端点端到端：真 DefaultRCAEngine 产非空报告 --------------------


def test_rca_endpoint_returns_real_nonempty_report() -> None:
    """POST /api/rca/analyze(disk_full) → 200 + trace_id；GET → report 非空且含真引擎键。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                a = await client.post(
                    "/api/rca/analyze",
                    json={"problem_type": "disk_full", "description": "根分区满"},
                )
                assert a.status_code == 200
                trace_id = a.json()["trace_id"]

                g = await client.get(f"/api/rca/{trace_id}")
                assert g.status_code == 200
                report = g.json()["report"]
                # 接真后报告必须非空（NullRCA 时此处为 {}）
                assert report, "DefaultRCAEngine 对明确 problem_type 应产非空报告"
                assert report["problem_type"] == "disk_full"
                # 命中 DefaultRCAEngine 的稳定输出结构
                for key in _RCA_REPORT_KEYS:
                    assert key in report, f"report 缺少 DefaultRCAEngine 键: {key}"
                assert isinstance(report["root_cause_candidates"], list)

    asyncio.run(scenario())


def test_rca_provider_returns_default_engine() -> None:
    """get_rca provider 已接真：返回 DefaultRCAEngine（非 NullRCA 桩）。"""
    engine = get_rca()
    assert isinstance(engine, DefaultRCAEngine)


# ---- 2. 主链路注入：chat 构造的 Orchestrator 注入真 DefaultRCAEngine -------


def test_chat_orchestrator_injected_with_default_rca() -> None:
    """POST /api/chat 后，registry 中会话的 orchestrator._rca 是真 DefaultRCAEngine。

    聚焦"接线正确"：证明 chat 链路注入的是真引擎而非默认 NullRCA。
    """

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                resp = await client.post("/api/chat", json={"message": "看下系统"})
                assert resp.status_code == 200
                trace_id = resp.json()["trace_id"]
                session = registry.get(trace_id)
                assert session is not None
                # 接线正确：注入的是真 DefaultRCAEngine（默认会是 NullRCA）
                assert isinstance(session.orchestrator._rca, DefaultRCAEngine)

    asyncio.run(scenario())


# ---- 3. 调起点连通：真证据下 orchestrator emit "rca" 事件 ------------------


class _Audit:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


class _Events:
    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    def emit(self, event: StreamEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type for e in self.events]


class _DiskEvidenceExecutor:
    """注入桩：返回带 disk.usage 高水位证据的 ToolResult（驱动命中 disk_full）。"""

    async def execute(self, tool: CandidateTool) -> ToolResult:
        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=0,
            stdout_truncated="/dev/sda1 95% /var/log no space left on device",
            is_untrusted=True,
        )


class _AllowPolicy:
    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return PolicyVerdict(
            decision="allow",
            final_risk="R0",
            matched_rules=[],
            reason="allow for rca wiring test",
            approval_required=False,
        )


def _llm(intent_obj: dict) -> LLMAdapter:
    payload = json.dumps(intent_obj)

    async def fn(messages):  # noqa: ANN001
        return payload

    return LLMAdapter(completion_fn=fn)


def test_orchestrator_emits_rca_event_with_default_engine() -> None:
    """真 DefaultRCAEngine 注入 + 会命中 disk_full 的证据 → emit 契约6 "rca" 事件，report 非空。

    证明 orchestrator VERIFIED 后的 RCA 调起点端到端连通（非桩永空）。
    """
    from backend.app.contracts.tool import ToolSpec

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="disk.usage",
            description="查看磁盘使用率",
            risk="R0",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            requires_roles=["operator"],
            reversible=True,
        )
    )
    gateway = MCPGateway(registry, _AllowPolicy(), _DiskEvidenceExecutor())  # type: ignore[arg-type]
    audit, events = _Audit(), _Events()
    intent_obj = {
        "intent": "disk_check",
        "confidence": 0.9,
        "need_observation": False,
        "candidate_tools": [{"name": "disk.usage", "args": {}}],
        "risk_hint": "low",
        "justification": "rca wiring",
    }
    orch = Orchestrator(
        llm=_llm(intent_obj),
        gateway=gateway,
        audit=audit,
        events=events,
        rca=DefaultRCAEngine(),
        trace_id="rca-wiring",
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "看磁盘"}]))

    assert end is State.FINISHED
    assert "rca" in events.types(), "命中 disk_full 证据应 emit rca 事件"
    rca_events = [e for e in events.events if e.type == "rca"]
    report = rca_events[0].data["report"]
    assert report, "rca 事件 report 应非空"
    assert report["problem_type"] == "disk_full"
