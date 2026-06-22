"""L1 — fake→real 策略集成验证哨兵（端到端）。

D 的真 PolicyEngine 已合入并从 backend.app.security 导出，本哨兵**已激活**（实跑非 skip）。
装配方式：真 ToolRegistry(os_ops all_specs()) + 真 DEFAULT_POLICY + 真 PolicyEngine，
Executor 仍用 FakeExecutor（不实现 D 的执行层；C3 红线）。端到端断言策略实质成立。

注（L-2 整改）：原有 try/except ImportError 待命守卫已删除——真件已合入，import 失败
应如实 ERROR（守卫只会在环境损坏时伪装成 "1 skipped" 静默下线，是风险而非保护）。

【与 D 的接线契约】：PolicyEngine(policy: PolicySet, registry: ToolRegistry)；
evaluate(tool) -> PolicyVerdict（contracts.policy 冻结）。构造若变更，改 _make_engine()。
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
from backend.app.security import DEFAULT_POLICY, PolicyEngine
from mcp_servers.os_ops import all_specs

# ---- fakes（仅 Executor/audit/events/llm；策略与注册表用真件）-------------


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, tool: CandidateTool) -> ToolResult:
        self.calls.append(tool.name)
        return ToolResult(tool=tool.name, args=tool.args, exit_code=0, stdout_truncated="ok")


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


def _llm(intent_obj: dict) -> LLMAdapter:
    payload = json.dumps(intent_obj)

    async def fn(messages):  # noqa: ANN001
        return payload

    return LLMAdapter(completion_fn=fn)


def _make_engine(registry: ToolRegistry) -> object:
    """构造 D 的真 PolicyEngine（接线约定见模块头：(policy, registry)）。"""
    return PolicyEngine(DEFAULT_POLICY, registry)


def _build(intent_obj: dict) -> tuple[Orchestrator, _Audit, _Events, _RecordingExecutor]:
    registry = ToolRegistry(all_specs())
    executor = _RecordingExecutor()
    gateway = MCPGateway(registry, _make_engine(registry), executor)  # type: ignore[arg-type]
    audit, events = _Audit(), _Events()
    orch = Orchestrator(
        llm=_llm(intent_obj), gateway=gateway, audit=audit, events=events, trace_id="real-policy"
    )
    return orch, audit, events, executor


def _action_plan(tools: list[dict], *, risk_hint: str = "low") -> dict:
    return {
        "intent": "real_policy_e2e",
        "confidence": 0.9,
        "need_observation": False,
        "candidate_tools": tools,
        "risk_hint": risk_hint,
        "justification": "real policy integration test",
    }


# ---- 断言策略实质成立 -----------------------------------------------------


def test_readonly_r0_r1_allow_runs_to_verified() -> None:
    """R0/R1 只读工具 → allow → 执行到 VERIFIED/FINISHED。"""
    orch, _audit, events, executor = _build(_action_plan([{"name": "disk.usage", "args": {}}]))
    end = asyncio.run(orch.run([{"role": "user", "content": "看磁盘"}]))
    assert end is State.FINISHED
    assert executor.calls == ["disk.usage"]
    assert "verified" in events.types()


def test_r2_change_tool_confirm_operator_then_execute() -> None:
    """R2 工具(log.compress_rotate) → confirm/operator → WAIT_APPROVAL → resume → 执行。"""
    orch, _audit, events, executor = _build(
        _action_plan(
            [{"name": "log.compress_rotate", "args": {"path": "/var/log"}}],
            risk_hint="medium",
        )
    )
    paused = asyncio.run(orch.run([{"role": "user", "content": "压缩日志"}]))
    assert paused is State.WAIT_APPROVAL
    aa = [e for e in events.events if e.type == "await_approval"][0]
    roles = {t["approval_role"] for t in aa.data["tools"]}
    assert roles == {"operator"}  # R2 → operator 审批
    end = asyncio.run(orch.resume(approved=True))
    assert end is State.FINISHED
    assert executor.calls == ["log.compress_rotate"]


def test_r3_service_restart_confirm_admin_then_execute() -> None:
    """R3 工具(service.restart) → confirm/admin → 审批后执行。"""
    orch, _audit, events, executor = _build(
        _action_plan(
            [{"name": "service.restart", "args": {"service_name": "nginx.service"}}],
            risk_hint="high",
        )
    )
    paused = asyncio.run(orch.run([{"role": "user", "content": "重启 nginx"}]))
    assert paused is State.WAIT_APPROVAL
    aa = [e for e in events.events if e.type == "await_approval"][0]
    roles = {t["approval_role"] for t in aa.data["tools"]}
    assert roles == {"admin"}  # R3 → admin 审批
    end = asyncio.run(orch.resume(approved=True))
    assert end is State.FINISHED
    assert executor.calls == ["service.restart"]


def test_deny_rule_rejects_whole_plan_no_execution() -> None:
    """命中 deny 规则（FILE001：args 含 /etc/shadow）→ 整批 REJECTED、executor 不被调用。

    用 schema-valid 的只读工具承载触发 deny 的路径参数（log.large_log_scan path），
    确认拦截来自策略 deny 而非结构校验（路径绝对、无 ..，schema 放行）。
    """
    orch, _audit, events, executor = _build(
        _action_plan([{"name": "log.large_log_scan", "args": {"path": "/etc/shadow"}}])
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "扫描"}]))
    assert end is State.REJECTED
    assert executor.calls == []
    # 整批裁决为 deny
    pv = [e for e in events.events if e.type == "policy_verdict"][0]
    assert pv.data["verdict"]["decision"] == "deny"


def test_batch_with_one_deny_rejects_all_atomic_plan() -> None:
    """原子计划：批次含一个 deny（/etc/passwd）→ 整批不执行，allow 工具也不执行。"""
    orch, _audit, _events, executor = _build(
        _action_plan(
            [
                {"name": "disk.usage", "args": {}},  # allow
                {"name": "log.large_log_scan", "args": {"path": "/etc/passwd"}},  # deny
            ]
        )
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "混合计划"}]))
    assert end is State.REJECTED
    assert executor.calls == []  # 含禁止动作的计划整体不执行（原子语义）
