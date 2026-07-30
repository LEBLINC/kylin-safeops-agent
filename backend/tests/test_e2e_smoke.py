"""D12 端到端 smoke：观测→二次规划→多工具逐裁决→审批→批量执行→审计链完整。

含【参考 PolicyEngine stub】RiskBasedPolicy（按 ToolSpec.risk 给默认三态）。
TODO(BLOCKED-ON-EXECUTOR): 这是参考实现，真实 PolicyEngine（规则/角色/上下文裁决）
归 backend/app/security；此处仅为联调占位，不实现该模块。
"""

from __future__ import annotations

import asyncio
import json

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.state_machine import State
from backend.app.contracts.audit import GENESIS_HASH, AuditRecord, compute_curr_hash
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.stream import StreamEvent
from backend.app.contracts.untrusted import ToolResult
from backend.app.llm.adapter import LLMAdapter
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from mcp_servers.os_ops import all_specs


class RiskBasedPolicy:
    """参考 PolicyEngine stub：按注册表里工具的 risk 给默认三态裁决。

    R0/R1 → allow；R2 → confirm(operator)；R3/R4 → confirm(admin)。
    TODO(BLOCKED-ON-EXECUTOR): 真实策略引擎按 shieldset 规则/角色/参数上下文裁决，归安全层。
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        spec = self._registry.get(tool.name)
        risk = spec.risk if spec else "R4"
        if risk in ("R0", "R1"):
            return PolicyVerdict(
                decision="allow",
                final_risk=risk,
                matched_rules=[f"risk:{risk}"],
                reason="read-only",
                approval_required=False,
            )
        role = "admin" if risk in ("R3", "R4") else "operator"
        return PolicyVerdict(
            decision="confirm",
            final_risk=risk,
            matched_rules=[f"risk:{risk}"],
            reason="change requires approval",
            approval_required=True,
            approval_role=role,
        )


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


def _seq_llm(*outputs: str) -> LLMAdapter:
    seq = list(outputs)
    calls = {"n": 0}

    async def fn(messages):  # noqa: ANN001
        out = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return out

    return LLMAdapter(completion_fn=fn)


def _assert_chain(records: list[AuditRecord]) -> None:
    prev = GENESIS_HASH
    for i, rec in enumerate(records):
        assert rec.seq == i
        assert rec.prev_hash == prev
        assert rec.curr_hash == compute_curr_hash(prev, rec.payload)
        prev = rec.curr_hash


def test_e2e_observe_replan_multitool_approval_execute_audit() -> None:
    """4 工具端到端：观测(只读) → 二次规划(4 工具混合) → 审批 → 批量执行 → 审计链完整。"""
    registry = ToolRegistry(all_specs())
    executor = _RecordingExecutor()
    gateway = MCPGateway(registry, RiskBasedPolicy(registry), executor)
    audit, events = _Audit(), _Events()

    # 首次规划：需观测，候选只读 disk.usage（R0）
    first = json.dumps(
        {
            "intent": "triage_disk",
            "confidence": 0.9,
            "need_observation": True,
            "candidate_tools": [{"name": "disk.usage", "args": {}}],
            "risk_hint": "low",
            "justification": "先观测磁盘",
        }
    )
    # 二次规划：4 工具混合（2 个 R0 allow + 2 个 R2/R3 confirm）
    second = json.dumps(
        {
            "intent": "act_disk",
            "confidence": 0.9,
            "need_observation": False,
            "candidate_tools": [
                {"name": "disk.usage", "args": {}},
                {"name": "network.ports", "args": {}},
                {"name": "log.compress_rotate", "args": {"path": "/var/log"}},
                {"name": "service.restart", "args": {"service_name": "nginx.service"}},
            ],
            "risk_hint": "high",
            "justification": "据观测执行处置",
        }
    )
    orch = Orchestrator(llm=_seq_llm(first, second), gateway=gateway, audit=audit, events=events)

    # 观测阶段只执行只读 disk.usage
    paused = asyncio.run(orch.run([{"role": "user", "content": "磁盘满了处理一下"}]))
    assert paused is State.WAIT_APPROVAL  # 含 R2/R3 → 整批待审批
    assert executor.calls == ["disk.usage"]  # 仅观测阶段执行了只读工具

    # 审批面板列出的 confirm 工具 == 两个变更工具
    aa = [e for e in events.events if e.type == "await_approval"][0]
    assert {t["tool"] for t in aa.data["tools"]} == {"log.compress_rotate", "service.restart"}

    # 批准 → 按序执行全部 4 个行动工具
    end = asyncio.run(orch.resume(approved=True))
    assert end is State.FINISHED
    assert executor.calls == [
        "disk.usage",  # 观测
        "disk.usage",
        "network.ports",
        "log.compress_rotate",
        "service.restart",
    ]
    # 全链路事件齐备
    for t in (
        "intent_parsed",
        "observation",
        "plan_generated",
        "policy_verdict",
        "await_approval",
        "executing",
        "tool_result",
        "verified",
    ):
        assert t in events.types()
    # 审计哈希链贯穿观测→规划→裁决→审批→逐工具执行→核验，连续可复算
    _assert_chain(audit.records)
