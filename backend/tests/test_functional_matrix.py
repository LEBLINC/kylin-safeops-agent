"""D19 功能测试矩阵 F001–F006 脚手架（提案，★待 L 确认编号）。

矩阵定义见 docs/design/functional-test-matrix.md。

原则：happy-path 管道断言（终态/执行序/关键事件）；不硬编"安全拦截"断言。
依赖 D 真 PolicyEngine 的 F005 用 module/用例级 skip 待命（同 L1 哨兵套路），D 合入即激活。
"""

from __future__ import annotations

import asyncio
import json

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.state_machine import State
from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.stream import StreamEvent
from backend.app.contracts.untrusted import ToolResult
from backend.app.llm.adapter import LLMAdapter
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from mcp_servers.os_ops import all_specs
from scripts._demo_common import RiskBasedPolicy

# ---- 复用演示参考桩装配（fake 协作者）------------------------------------


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
    gateway = MCPGateway(registry, RiskBasedPolicy(registry), executor)
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
        tools=[{"name": "log.compress_rotate", "args": {"path": "/var/log", "keep": 3}}],
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
    assert ex.calls == ["config.hash_snapshot", "config.diff"]
    tr = [e for e in events.events if e.type == "tool_result"]
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

    L-2 整改：D 的 PolicyEngine 已从 backend.app.security 导出，原 try/except skip
    守卫已删除——import 失败应如实 ERROR，不再静默 skip。
    """
    from backend.app.security import DEFAULT_POLICY, PolicyEngine

    registry = ToolRegistry(all_specs())
    executor = _Executor()
    gateway = MCPGateway(registry, PolicyEngine(DEFAULT_POLICY, registry), executor)
    audit, events = _Audit(), _Events()
    orch = Orchestrator(
        llm=_llm(
            _intent(
                need_observation=False,
                tools=[{"name": "log.large_log_scan", "args": {"path": "/etc/shadow"}}],
            )
        ),
        gateway=gateway,
        audit=audit,
        events=events,
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "扫描"}]))
    assert end is State.REJECTED
    assert executor.calls == []


# ---- F006 SSE 端到端：已由 test_api_endpoints 覆盖（登记，不重复装配）----


def test_f006_sse_e2e_covered_elsewhere() -> None:
    """F006(SSE 事件流端到端) 已由 test_api_endpoints::test_chat_post_then_sse_to_done 覆盖。

    此处仅登记矩阵条目并校验被引测试存在（按文件内容核验，避免导入测试模块/重复装配）。
    """
    from pathlib import Path

    covering = Path(__file__).with_name("test_api_endpoints.py")
    assert covering.is_file()
    assert "def test_chat_post_then_sse_to_done" in covering.read_text(encoding="utf-8")
