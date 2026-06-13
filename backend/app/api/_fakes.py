"""联调注入桩集中地（待 D/X 真实现替换）。

本文件所有内容均为【注入桩 / fake】，仅用于联调与空跑。

═══════════════════════════════════════════════════════════════════
注入点替换清单（接线状态留痕）
═══════════════════════════════════════════════════════════════════
三个协作者件，真实现均归 D（C3 越界红线：L 侧不实现 evaluate/execute/append）：

  ① PolicyEngine（策略裁决）✅ 已切真
     现状：build_gateway() 已注入 D 的真 PolicyEngine(DEFAULT_POLICY, registry)。
     桩 FakePolicyEngine 保留供测试按需注入 allow-all 场景。

  ② Executor（特权代理执行）✅ 已切真
     现状：build_gateway() 已注入 D 的真 PrivilegeExecutor（无参构造）。
     桩 FakeExecutor 保留供测试按需注入（dependency_overrides）成功罐头场景。

  ③ AuditSink（哈希链审计落库）✅ 已切真
     现状：app.get_audit() 返回 lifespan 单例 SqliteAuditSink（持 DB 句柄+链状态）。
     桩 FakeAudit 保留供测试无落库场景。

另含 LLM 注入桩（待接真实 LLM 端点，非 D 模块）：
     桩：build_fake_llm（本文件）；接线处：app.get_llm() provider。

装配点：app.py 的 build_gateway / get_audit / get_llm 三个 provider；
config.diff 暂缓注册见 _DEFERRED_TOOLS。
═══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json

from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.untrusted import ToolResult
from backend.app.executor import PrivilegeExecutor
from backend.app.llm.adapter import LLMAdapter, Message
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from backend.app.security import DEFAULT_POLICY, PolicyEngine
from mcp_servers.os_ops import all_specs

#: app 注册集中暂缓注册的工具（L 域 registry 装配过滤，不碰 os_ops 工具声明本身）。
#: config.diff 需快照基线聚合、无单命令模板，真执行会返 127——待 D 执行层支持或
#: L 在 mcp 层做聚合后再注册。后果：config.diff 不在 /api/tools/registry；若 intent
#: 提议它 → gateway 闸1（未注册）→ 安全降级 deny（已知会 X）。
_DEFERRED_TOOLS = {"config.diff"}


class FakePolicyEngine:
    """注入桩：永远 allow。

    注：默认 app 装配已切换为 D 的真 PolicyEngine（见 build_gateway）；
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
    """注入桩：永远返回成功空结果。app 已切真 PrivilegeExecutor；本桩仅供测试注入。"""

    async def execute(self, tool: CandidateTool) -> ToolResult:
        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=0,
            stdout_truncated="[fake] executed successfully",
            is_untrusted=True,
        )


class FakeAudit:
    """注入桩：审计落库空操作。app 已切真 SqliteAuditSink 单例；本桩仅供测试无落库场景。"""

    def append(self, record: AuditRecord) -> None:
        return None


def build_fake_audit() -> FakeAudit:
    """装配 fake AuditSink（注入桩，仅供测试；app 已用真 SqliteAuditSink 单例）。"""
    return FakeAudit()


def build_gateway() -> MCPGateway:
    """装配默认 MCPGateway：【真 registry + 真策略 + 真特权执行器】。

    现状（全真，除 config.diff 暂缓注册）：
    - registry：真 os_ops 工具集 all_specs()，过滤掉 _DEFERRED_TOOLS（config.diff）。
    - policy：D 的真 PolicyEngine(DEFAULT_POLICY, registry)——同一 registry 实例防漂移。
    - executor：D 的真 PrivilegeExecutor（无参构造，默认 timeout=30 + DEFAULT_POLICY）。

    切真后运行中的 app 会经特权代理跑真命令（方案B：失败用 exit_code 承载，仅系统级故障 raise）。
    LLM/审计经各自 provider（get_llm/get_audit）注入，不在本装配点。
    config.diff 暂从注册集摘除（见 _DEFERRED_TOOLS）。
    """
    specs = [s for s in all_specs() if s.name not in _DEFERRED_TOOLS]
    registry = ToolRegistry(specs)
    return MCPGateway(
        registry=registry,
        policy=PolicyEngine(DEFAULT_POLICY, registry),
        executor=PrivilegeExecutor(),  # type: ignore[arg-type]
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
