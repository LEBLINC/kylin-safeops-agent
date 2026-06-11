"""联调注入桩集中地（待 D/X 真实现替换）。

本文件所有内容均为【注入桩 / fake】，仅用于联调与空跑。

═══════════════════════════════════════════════════════════════════
注入点替换清单（D 模块就绪后，改下列对应处即可，替换面收敛于此）
═══════════════════════════════════════════════════════════════════
三个协作者注入桩，真实现均归 D（C3 越界红线：L 侧不实现 evaluate/execute/append）：

  ① PolicyEngine（策略裁决）✅ 已切真
     现状：build_fake_gateway() 已注入 D 的真 PolicyEngine(DEFAULT_POLICY, registry)。
     桩 FakePolicyEngine 保留供测试按需注入 allow-all 场景。

  ② Executor（特权代理执行）🔴 仍桩
     桩：FakeExecutor.execute（本文件，返回成功空结果）
     真模块：backend/app/executor（D 实现 Executor.execute，PR2）
     接线处：build_fake_gateway() 的 executor=... → 换成 D 的 Executor 实例

  ③ AuditSink（哈希链审计落库）🟡 落库仍桩
     桩：FakeAudit.append（本文件，空操作）
     真模块：backend/app/audit（D 实现 audit_logger）
     接线处：app.get_audit() provider → 换成 D 的 AuditSink 实例

另含 LLM 注入桩（待接真实 LLM 端点，非 D 模块）：
     桩：build_fake_llm（本文件）；接线处：app.get_llm() provider。

切换方式：app.py 的 build_fake_gateway / get_audit / get_llm 三个 provider 是唯一接线点，
改它们的 import 指向真模块即可，不必在路由/lifespan 里翻找内联桩。
═══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json

from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.untrusted import ToolResult
from backend.app.llm.adapter import LLMAdapter, Message
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from backend.app.security import DEFAULT_POLICY, PolicyEngine
from mcp_servers.os_ops import all_specs


class FakePolicyEngine:
    """注入桩：永远 allow。

    注：默认 app 装配已切换为 D 的真 PolicyEngine（见 build_fake_gateway）；
    本桩保留供测试按需注入（dependency_overrides）构造 allow-all 场景。
    """

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return PolicyVerdict(
            decision="allow",
            final_risk="R0",
            matched_rules=[],
            reason="fake policy: allow all",
            approval_required=False,
        )


class FakeExecutor:
    """注入桩：永远返回成功空结果。待 D 的 Executor 真实现替换（PR2）。"""

    async def execute(self, tool: CandidateTool) -> ToolResult:
        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=0,
            stdout_truncated="[fake] executed successfully",
            is_untrusted=True,
        )


class FakeAudit:
    """注入桩：审计落库空操作。待 D 的 audit_logger（哈希链落库）真实现替换。"""

    def append(self, record: AuditRecord) -> None:
        return None


def build_fake_audit() -> FakeAudit:
    """装配 fake AuditSink（注入桩，待 D 的 backend/app/audit 真实现替换）。"""
    return FakeAudit()


def build_fake_gateway() -> MCPGateway:
    """装配默认 MCPGateway：【真 registry + 真策略 + fake 执行器】。

    现状（非全 fake）：
    - registry：真 os_ops 工具集 all_specs()（13 工具），策略闸据此实质裁决。
    - policy：D 的真 PolicyEngine(DEFAULT_POLICY, registry)——同一 registry 实例防漂移。
    - executor：仍 FakeExecutor（D 的 Executor PR2 未合，本层不跑真命令）。

    待 D 的 Executor 合入后，仅需把 executor 换成真 Executor（唯一剩余切换点）。
    """
    registry = ToolRegistry(all_specs())
    return MCPGateway(
        registry=registry,
        policy=PolicyEngine(DEFAULT_POLICY, registry),
        executor=FakeExecutor(),  # type: ignore[arg-type]
    )


# 默认 fake 意图：提议真只读工具 system.info（R0）——真策略下 allow→执行→verified。
_FAKE_INTENT_JSON = json.dumps(
    {
        "intent": "system_info",
        "confidence": 0.9,
        "need_observation": False,
        "candidate_tools": [{"name": "system.info", "args": {}}],
        "risk_hint": "low",
        "justification": "查看系统基本信息（fake 规划）",
    }
)


def build_fake_llm(intent_json: str | None = None) -> LLMAdapter:
    """装配 fake LLMAdapter（注入桩，不联网，待接真实 LLM 端点替换）。

    注入一个 completion_fn 永远返回固定 Intent JSON，使 orchestrator 可空跑主链路。
    """
    payload = intent_json or _FAKE_INTENT_JSON

    async def _fixed_completion(messages: list[Message]) -> str:
        return payload

    return LLMAdapter(completion_fn=_fixed_completion)
