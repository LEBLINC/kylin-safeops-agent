"""MCP Gateway（手册 §3.3）。

tools/list 与 tools/call。tools/call 的执行**强制**经过三道闸，顺序不可调换：
  1. 注册校验：工具必须已注册（未注册即拒，防影子工具）。
  2. 结构校验：args 按 ToolSpec.input_schema 过 schema_validator（策略前第一道闸）。
  3. 策略放行：过 D 的 PolicyEngine；非 allow 一律不执行。
放行后才交注入的 Executor 执行；结果一律包成契约4 ToolResult(is_untrusted=True)。

本层不直接跑命令、不拼 shell（铁律2）；执行委托 Executor（D 实现）。
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.agent.ports import Executor, PolicyEngine
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.tool import ToolSpec
from backend.app.contracts.untrusted import ToolResult
from backend.app.mcp.registry import ToolRegistry
from backend.app.mcp.schema_validator import validate_args


@dataclass
class CallOutcome:
    """tools/call 的结果。

    executed=True 时 result 为执行结果；executed=False 时被某道闸拦下，
    reason 给出原因，verdict 在策略拦下时携带裁决（供前端/审计展示）。
    """

    executed: bool
    result: ToolResult | None = None
    verdict: PolicyVerdict | None = None
    reason: str = ""


def _deny_verdict(reason: str) -> PolicyVerdict:
    """为结构校验/注册失败合成一个 deny 裁决（语义统一）。"""
    return PolicyVerdict(
        decision="deny",
        final_risk="R0",
        matched_rules=[],
        reason=reason,
        approval_required=False,
    )


class MCPGateway:
    """工具网关：列举与受控调用。

    policy/executor 注入（D 实现）。本类只编排三道闸 + 结果闸，不实现它们。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        policy: PolicyEngine,
        executor: Executor,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._executor = executor

    def list_tools(self) -> list[ToolSpec]:
        """tools/list：返回已注册工具规格。"""
        return self._registry.list_tools()

    async def call(self, tool: CandidateTool) -> CallOutcome:
        """tools/call：三道闸 → 执行 → 结果闸。任一闸不过则不执行。"""
        # 闸1：注册校验
        spec = self._registry.get(tool.name)
        if spec is None:
            return CallOutcome(
                executed=False,
                verdict=_deny_verdict(f"unknown tool: {tool.name}"),
                reason="unregistered tool",
            )

        # 闸2：结构校验（策略前第一道；不过直接 deny）
        sv = validate_args(tool.args, spec.input_schema)
        if not sv.ok:
            reason = "schema validation failed: " + "; ".join(sv.errors)
            return CallOutcome(executed=False, verdict=_deny_verdict(reason), reason=reason)

        # 闸3：策略放行（仅 allow 执行；confirm/deny 不在网关层执行）
        verdict = self._policy.evaluate(tool)
        if verdict.decision != "allow":
            return CallOutcome(
                executed=False, verdict=verdict, reason=f"policy: {verdict.decision}"
            )

        # 执行 + 结果闸：强制不可信标记
        result = await self._executor.execute(tool)
        if not result.is_untrusted:
            result = result.model_copy(update={"is_untrusted": True})
        return CallOutcome(executed=True, result=result, verdict=verdict)
