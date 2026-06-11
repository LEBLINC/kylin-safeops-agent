"""L3 — 演示剧本脚手架：磁盘满 → 观测 → 规划 → 审批 → 执行 → verified（一键跑）。

评分演示用：跑通"用户报磁盘满 → Agent 观测磁盘 → 二次规划压缩轮转(R2 变更) →
策略 confirm → 人工审批 → 执行 → VERIFIED"的完整主链路，逐事件打印到控制台。

当前【跑在 fake 上】：
- LLM：注入桩（_fakes.build_fake_llm 的两段式剧本意图，不联网）。
- Executor：FakeExecutor（不跑真命令）。
- Policy：参考 RiskBasedPolicy（按 risk 三态）——演示审批闸；D 真件到位后翻真见文末。

D/X 真件到位后翻真：
- 策略换 backend.app.security 的真 PolicyEngine(DEFAULT_POLICY)；
- Executor 换 D 的特权代理 Executor；
- LLM 换真实端点（backend.app.llm.adapter 默认 httpx 实现 + LLMConfig）。

运行：python -m scripts.demo_disk_full_playbook   （仓库根目录下执行）
"""

from __future__ import annotations

import asyncio
import json

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.state_machine import State
from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.stream import StreamEvent
from backend.app.contracts.untrusted import ToolResult
from backend.app.llm.adapter import LLMAdapter
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from mcp_servers.os_ops import all_specs


class _RiskBasedPolicy:
    """演示用参考策略：R0/R1→allow，R2→confirm/operator，R3/R4→confirm/admin。

    仅供演示审批闸；真件为 backend.app.security 的 PolicyEngine(DEFAULT_POLICY)。
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


class _DemoExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, tool: CandidateTool) -> ToolResult:
        self.calls.append(tool.name)
        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=0,
            stdout_truncated=f"[demo] {tool.name} executed",
        )


class _PrintEvents:
    """把流式事件打印到控制台（演示可视化）。"""

    def emit(self, event: StreamEvent) -> None:
        data = json.dumps(event.data, ensure_ascii=False)
        if len(data) > 160:
            data = data[:157] + "..."
        print(f"  [event] {event.type:<16} {data}")


class _SilentAudit:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


# 两段式剧本意图：先观测磁盘（只读），再规划压缩轮转（R2 变更，触发审批）。
_OBSERVE_INTENT = json.dumps(
    {
        "intent": "diagnose_disk_full",
        "confidence": 0.95,
        "need_observation": True,
        "candidate_tools": [{"name": "disk.usage", "args": {}}],
        "risk_hint": "low",
        "justification": "先观测各挂载点占用，定位满盘分区",
    }
)
_ACTION_INTENT = json.dumps(
    {
        "intent": "reclaim_disk_space",
        "confidence": 0.9,
        "need_observation": False,
        "candidate_tools": [
            {"name": "log.compress_rotate", "args": {"path": "/var/log", "keep": 3}}
        ],
        "risk_hint": "medium",
        "justification": "据观测，/var/log 占用偏高，压缩轮转回收空间",
    }
)


def _demo_llm() -> LLMAdapter:
    seq = [_OBSERVE_INTENT, _ACTION_INTENT]
    calls = {"n": 0}

    async def fn(messages: list[dict[str, str]]) -> str:
        out = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return out

    return LLMAdapter(completion_fn=fn)


async def run_playbook() -> State:
    """跑完整剧本：观测→规划→审批→执行→verified。返回终态。"""
    registry = ToolRegistry(all_specs())
    executor = _DemoExecutor()
    gateway = MCPGateway(registry, _RiskBasedPolicy(registry), executor)
    orch = Orchestrator(
        llm=_demo_llm(),
        gateway=gateway,
        audit=_SilentAudit(),
        events=_PrintEvents(),
        trace_id="demo-disk-full",
    )

    print("=" * 64)
    print("剧本：用户报『磁盘满了，帮我处理』")
    print("=" * 64)
    print("[1] run：观测磁盘 → 二次规划压缩轮转 → 策略裁决")
    state = await orch.run(
        [{"role": "user", "content": "磁盘满了，帮我清理一下"}],
        user_intent="磁盘满了，帮我清理一下",
    )
    print(f"  -> 暂停状态：{state.value}")

    if state is State.WAIT_APPROVAL:
        print("[2] 人工审批闸：operator 批准 log.compress_rotate")
        state = await orch.resume(approved=True)
        print(f"  -> 续跑终态：{state.value}")

    print("-" * 64)
    print(f"执行的工具：{executor.calls}")
    print(f"终态：{state.value}（期望 FINISHED）")
    print("=" * 64)
    return state


def main() -> None:
    state = asyncio.run(run_playbook())
    if state is not State.FINISHED:
        raise SystemExit(f"演示未达 FINISHED，实际：{state.value}")


if __name__ == "__main__":
    main()
