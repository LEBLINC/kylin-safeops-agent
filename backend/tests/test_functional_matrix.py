"""D19 功能测试矩阵 F001–F006（任务B：F001–F004 接真 PolicyEngine + F006 真 SSE 行为）。

矩阵定义：F001 只读单工具链路 / F002 观测→二次规划→审批→执行 / F003 多工具原子计划
（全 allow）/ F004 高危 R3 审批闸（批准/拒绝两路）/ F005 危险命令策略拦截 /
F006 SSE 端到端真行为（详见下方各节注释）。

原则：happy-path 管道断言（终态/执行序/关键事件）；不硬编"安全拦截"断言。

任务B 整改：
- F001–F004 原跑在 scripts._demo_common.RiskBasedPolicy **桩**上，现统一注入真
  PolicyEngine(DEFAULT_POLICY, registry)（真件已合入，top-level import，**不加待命守卫**）。
  断言已核对真裁决：F001 只读→allow→FINISHED；F002 log.compress_rotate(R2,/var/log)→
  operator 审批；F004 service.restart(R3)→admin 审批；F003 多只读(R0,/etc 配置)→allow 原子执行
  （只读工具不触发 forbid_modify，/etc 配置不命中 FILE001）。
- F005 已是真 PolicyEngine（保留独立装配）。
- F006 由"查另一文件函数名字符串"的伪测试**改为真 SSE 端到端行为测试**（真起 app 跑一条链、
  断言事件流到 done 且关键事件序正确）。
- RiskBasedPolicy 仍留在 scripts/_demo_common.py（演示参考桩，不删），本矩阵不再依赖它。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.state_machine import State
from backend.app.api.app import create_app, lifespan
from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.stream import StreamEvent
from backend.app.contracts.untrusted import ToolResult
from backend.app.llm.adapter import LLMAdapter
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from backend.app.security import DEFAULT_POLICY, PolicyEngine
from mcp_servers.os_ops import all_specs

# ---- 真件装配（真 registry + 真 PolicyEngine + fake 执行/审计/事件）-------


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


class _Executor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, tool: CandidateTool) -> ToolResult:
        self.calls.append(tool.name)
        return ToolResult(tool=tool.name, args=tool.args, exit_code=0, stdout_truncated="ok")


def _llm(*intents: str) -> LLMAdapter:
    seq = list(intents)
    calls = {"n": 0}

    async def fn(messages):  # noqa: ANN001
        out = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return out

    return LLMAdapter(completion_fn=fn)


def _build(*intents: str) -> tuple[Orchestrator, _Audit, _Events, _Executor]:
    registry = ToolRegistry(all_specs())
    executor = _Executor()
    # 任务B：注入真策略引擎（同一 registry 防漂移），脱离 RiskBasedPolicy 桩。
    gateway = MCPGateway(registry, PolicyEngine(DEFAULT_POLICY, registry), executor)
    audit, events = _Audit(), _Events()
    orch = Orchestrator(
        llm=_llm(*intents), gateway=gateway, audit=audit, events=events, trace_id="fmatrix"
    )
    return orch, audit, events, executor


def _intent(
    *, need_observation: bool, tools: list[dict], name: str = "fmatrix", hint: str = "low"
) -> str:
    return json.dumps(
        {
            "intent": name,
            "confidence": 0.9,
            "need_observation": need_observation,
            "candidate_tools": tools,
            "risk_hint": hint,
            "justification": "functional matrix",
        }
    )


# ---- F001 只读单工具链路 -------------------------------------------------


def test_f001_readonly_single_tool_to_finished() -> None:
    orch, _a, events, ex = _build(
        _intent(need_observation=False, tools=[{"name": "system.info", "args": {}}])
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "看系统信息"}]))
    assert end is State.FINISHED
    assert ex.calls == ["system.info"]
    assert "verified" in events.types()


# ---- F002 观测→二次规划→审批→执行 --------------------------------------


def test_f002_observe_replan_approve_execute() -> None:
    observe = _intent(need_observation=True, tools=[{"name": "disk.usage", "args": {}}])
    action = _intent(
        need_observation=False,
        tools=[{"name": "log.compress_rotate", "args": {"path": "/var/log"}}],
        hint="medium",
    )
    orch, _a, events, ex = _build(observe, action)
    paused = asyncio.run(orch.run([{"role": "user", "content": "磁盘满"}]))
    assert paused is State.WAIT_APPROVAL
    assert "observation" in events.types()
    end = asyncio.run(orch.resume(approved=True))
    assert end is State.FINISHED
    assert ex.calls == ["disk.usage", "log.compress_rotate"]


# ---- F003 多工具原子计划（全 allow）-------------------------------------


def test_f003_multi_tool_atomic_all_allow() -> None:
    paths = ["/etc/nginx/nginx.conf", "/etc/ssh/sshd_config"]
    orch, _a, events, ex = _build(
        _intent(
            need_observation=False,
            tools=[
                {"name": "config.hash_snapshot", "args": {"paths": paths}},
                {"name": "config.diff", "args": {"paths": paths, "baseline_id": "b1"}},
            ],
        )
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "查配置漂移"}]))
    assert end is State.FINISHED
    # 决策⑤：config.diff 在 mcp 层聚合，executor 实际收到的是其内部复用的 config.hash_snapshot
    # （绝不把 config.diff 落给 D 单命令执行器）；故 executor 见两次 config.hash_snapshot。
    assert ex.calls == ["config.hash_snapshot", "config.hash_snapshot"]
    tr = [e for e in events.events if e.type == "tool_result"]
    # tool_result 的 tool 名仍是原计划工具（聚合结果回填 tool="config.diff"）。
    assert {e.data["result"]["tool"] for e in tr} == {"config.hash_snapshot", "config.diff"}


# ---- F004 高危 R3 审批闸（批准 / 拒绝两路）-------------------------------


def test_f004_r3_approval_gate_approved() -> None:
    orch, _a, events, ex = _build(
        _intent(
            need_observation=False,
            tools=[{"name": "service.restart", "args": {"service_name": "nginx.service"}}],
            hint="high",
        )
    )
    paused = asyncio.run(orch.run([{"role": "user", "content": "重启 nginx"}]))
    assert paused is State.WAIT_APPROVAL
    aa = [e for e in events.events if e.type == "await_approval"][0]
    assert {t["approval_role"] for t in aa.data["tools"]} == {"admin"}
    end = asyncio.run(orch.resume(approved=True))
    assert end is State.FINISHED
    assert ex.calls == ["service.restart"]


def test_f004_r3_approval_gate_rejected() -> None:
    orch, _a, _events, ex = _build(
        _intent(
            need_observation=False,
            tools=[{"name": "service.restart", "args": {"service_name": "nginx.service"}}],
            hint="high",
        )
    )
    asyncio.run(orch.run([{"role": "user", "content": "重启 nginx"}]))
    end = asyncio.run(orch.resume(approved=False))
    assert end is State.REJECTED
    assert ex.calls == []  # 拒绝审批 → 不执行


# ---- F005 危险命令策略拦截（D 真 evaluate 已合入，哨兵已激活）-----------


def test_f005_dangerous_command_denied_by_real_policy() -> None:
    """命中 deny 规则 → 整批 REJECTED、不执行（真 PolicyEngine 实证）。

    任务B：_build 已统一注入真 PolicyEngine，直接复用即可。
    """
    orch, _a, _events, ex = _build(
        _intent(
            need_observation=False,
            tools=[{"name": "log.large_log_scan", "args": {"path": "/etc/shadow"}}],
        )
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "扫描"}]))
    assert end is State.REJECTED
    assert ex.calls == []


# ---- F006 SSE 端到端真行为：起 app 跑一条链、断言事件流到 done ------------


def test_f006_sse_e2e_to_done() -> None:
    """F006：真起 app、POST /api/chat 拿 trace_id、消费 SSE，断言事件流到 done 且关键事件序正确。

    任务B：删除原"查 test_api_endpoints 文件含某函数名字符串"的伪断言，改为真 SSE 行为断言
    （httpx ASGITransport，不联网；默认 fake LLM 提议 system.info(R0)→真策略 allow→执行→verified）。
    lifespan 手动进入以初始化全局单例（ASGITransport 不触发 lifespan）。
    """

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/chat", json={"message": "看下系统"})
                assert resp.status_code == 200
                data = resp.json()
                trace_id = data["trace_id"]
                assert data["stream_url"] == f"/api/chat/{trace_id}/events"

                lines: list[str] = []
                # GAP-4：消费加轮次上限，防链路 hang（如 fake LLM 改成需审批工具）挂到 CI 超时。
                max_lines = 500
                async with client.stream("GET", data["stream_url"]) as r:
                    async for line in r.aiter_lines():
                        lines.append(line)
                        if "event: done" in line:
                            break
                        if len(lines) >= max_lines:
                            break
                body = "\n".join(lines)
                assert (
                    "event: done" in body
                ), "SSE 未在轮次上限内到达 done（疑似 hang 或事件序异常）"
                # 关键事件序：意图解析 → 裁决 → 验证 → 终态 done
                assert "intent_parsed" in body
                assert "policy_verdict" in body
                assert "verified" in body
                assert body.index("intent_parsed") < body.index("verified")

    asyncio.run(scenario())
