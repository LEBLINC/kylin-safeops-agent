"""D16 演示剧本公共装配（四场景复用，减少重复）。

提供：参考策略桩 / 演示执行器 / 事件打印 / 静默审计 + 编排器装配 + 脚本化 LLM +
统一驱动 run/（按需 resume）的 drive()。各场景剧本只声明"意图序列 + 叙事文案"。

全部【跑在 fake 上】（D/X 真件到位后翻真三处，见各剧本文末与 集成对齐备忘.md §3）：
- 策略 → backend.app.security 的 PolicyEngine(DEFAULT_POLICY, registry)；
- Executor → D 的特权代理 Executor；
- LLM → 真实端点（backend.app.llm.adapter 默认 httpx 实现 + LLMConfig）。

铁律：剧本只用 all_specs() 已注册工具，工具名/参数严格按各 ToolSpec.input_schema（C1/S2）。
仅串联 happy-path 管道；不写"安全拦截"硬断言（待 L1 哨兵在 D 真 evaluate 合入后验证）。
"""

from __future__ import annotations

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


class RiskBasedPolicy:
    """演示用参考策略：R0/R1→allow，R2→confirm/operator，R3/R4→confirm/admin。

    仅供演示审批闸；真件为 backend.app.security 的 PolicyEngine(DEFAULT_POLICY, registry)。
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


class DemoExecutor:
    """演示执行器桩：记录调用、返回成功空结果（不跑真命令）。"""

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


class PrintEvents:
    """把流式事件打印到控制台（演示可视化）。"""

    def emit(self, event: StreamEvent) -> None:
        data = json.dumps(event.data, ensure_ascii=False)
        if len(data) > 160:
            data = data[:157] + "..."
        print(f"  [event] {event.type:<16} {data}")


class SilentAudit:
    """审计桩：仅留存记录（哈希链计算在 orchestrator，落库待 D）。"""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


def scripted_llm(*intents_json: str) -> LLMAdapter:
    """按调用次序返回预置 Intent JSON 的桩 LLM（不联网）。"""
    seq = list(intents_json)
    calls = {"n": 0}

    async def fn(messages: list[dict[str, str]]) -> str:
        out = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return out

    return LLMAdapter(completion_fn=fn)


def build_orchestrator(llm: LLMAdapter, *, trace_id: str) -> tuple[Orchestrator, DemoExecutor]:
    """装配演示编排器（真 registry+gateway 三道闸 + 参考策略桩 + 演示执行器）。"""
    registry = ToolRegistry(all_specs())
    executor = DemoExecutor()
    gateway = MCPGateway(registry, RiskBasedPolicy(registry), executor)
    orch = Orchestrator(
        llm=llm,
        gateway=gateway,
        audit=SilentAudit(),
        events=PrintEvents(),
        trace_id=trace_id,
    )
    return orch, executor


async def drive(
    *,
    title: str,
    user_message: str,
    intents: list[str],
    trace_id: str,
    approve: bool = True,
) -> tuple[State, list[str]]:
    """统一驱动：run（按需 resume 审批），打印叙事与事件，返回 (终态, 执行序)。

    approve=True 时遇 WAIT_APPROVAL 自动批准续跑（演示人工确认闸放行路径）。
    """
    orch, executor = build_orchestrator(scripted_llm(*intents), trace_id=trace_id)

    print("=" * 64)
    print(title)
    print("=" * 64)
    print("[1] run：观测 → 规划 → 策略裁决")
    state = await orch.run([{"role": "user", "content": user_message}], user_intent=user_message)
    print(f"  -> run 暂停/终态：{state.value}")

    if state is State.WAIT_APPROVAL and approve:
        print("[2] 人工确认闸：审批放行 → 续跑执行")
        state = await orch.resume(approved=True)
        print(f"  -> resume 终态：{state.value}")

    print("-" * 64)
    print(f"执行的工具：{executor.calls}")
    print(f"终态：{state.value}")
    print("（注：演示执行器为桩 DemoExecutor，未触真命令；策略闸为参考桩 RiskBasedPolicy）")
    print("=" * 64)
    return state, executor.calls
