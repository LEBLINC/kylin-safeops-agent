"""MCP Gateway（手册 §3.3）。

tools/list 与 tools/call。tools/call 的执行**强制**经过三道闸，顺序不可调换：
  1. 注册校验：工具必须已注册（未注册即拒，防影子工具）。
  2. 结构校验：args 按 ToolSpec.input_schema 过 schema_validator（策略前第一道闸）。
  3. 策略放行：过策略引擎；非 allow 一律不执行。
放行后才交注入的 Executor 执行；结果一律包成契约4 ToolResult(is_untrusted=True)。

特例：``config.diff`` 在三道闸通过后于 **mcp 层聚合**（决策⑤），不落单命令特权执行器——
复用 ``config.hash_snapshot`` 取真实快照后与基线对比（见 ``config_diff`` 模块），保 D 执行器
"单命令模板"纯粹。

本层不直接跑命令、不拼 shell（铁律2）；执行委托 Executor（由 backend/app/executor 实现）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyEngine, PolicyVerdict
from backend.app.contracts.tool import ToolSpec
from backend.app.contracts.untrusted import ToolResult
from backend.app.mcp import config_diff
from backend.app.mcp.registry import ToolRegistry
from backend.app.mcp.result_gate import seal_result
from backend.app.mcp.schema_validator import validate_args
from mcp_servers.os_ops.parsers import parse_sha256sum_output


@runtime_checkable
class Executor(Protocol):
    """特权代理执行器接口（由 backend/app/executor 实现）。

    定义在 mcp 层（gateway 的直接依赖），避免 agent→mcp→agent 循环导入；
    agent.ports 从此处再导出，对上层保持单一引用点。
    放行后的工具调用交由此接口在 systemd 沙箱内执行；gateway 不直接跑命令。
    失败以非 0 exit_code 表达（方案 B），系统级故障抛异常由上层转 error。
    """

    async def execute(self, tool: CandidateTool) -> ToolResult: ...


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


# 只读风险等级：观测阶段只允许执行这些等级的工具（防御纵深，不只信策略放行）。
READ_ONLY_RISKS: frozenset[str] = frozenset({"R0", "R1"})


class MCPGateway:
    """工具网关：列举与受控调用。

    policy/executor 由外部注入。本类只编排三道闸 + 结果闸，不实现它们。
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
        # config.diff 的 mcp 层聚合基线（决策⑤；gateway 实例级内存基线，见 config_diff 模块）。
        self._config_diff = config_diff.ConfigDiffAggregator()

    def list_tools(self) -> list[ToolSpec]:
        """tools/list：返回已注册工具规格。"""
        return self._registry.list_tools()

    def is_read_only(self, tool: CandidateTool) -> bool:
        """工具是否为只读（注册表 risk ∈ READ_ONLY_RISKS）。

        未注册工具视为非只读（保守）。供观测阶段做防御纵深过滤：
        即便策略误放行变更工具，观测阶段也绝不执行非只读工具。
        """
        spec = self._registry.get(tool.name)
        return spec is not None and spec.risk in READ_ONLY_RISKS

    def _validate_tool_call(self, tool: CandidateTool) -> PolicyVerdict:
        """闸1 注册校验 + 闸2 schema 校验 + 闸3 策略裁决，返回裁决（**不执行**）。

        之七十五 M-1：从 call() 提取，供 call() 与 _aggregate_config_diff() 的内部
        快照调用共同复用。此前后者直接 self._executor.execute(snapshot_tool)，
        绕过三道闸——paths 来自 tool.args（模型可控），虽已随 config.diff 本身过完
        策略闸与路径闸、executor 内仍 canonicalize，但"内部构造的调用不过闸"本身
        就是闸链一致性缺口：日后 config.hash_snapshot 的 schema 或策略一旦收紧，
        这条内部路径不会同步生效。

        **刻意不复用 call()**：那会与"聚合只在 mcp 层"（决策⑤）冲突，并引入
        call → _aggregate_config_diff → call 递归。故只提取校验、不提取执行。
        """
        spec = self._registry.get(tool.name)
        if spec is None:
            return _deny_verdict(f"unknown tool: {tool.name}")
        sv = validate_args(tool.args, spec.input_schema)
        if not sv.ok:
            return _deny_verdict("schema validation failed: " + "; ".join(sv.errors))
        return self._policy.evaluate(tool)

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        """前两道闸 + 策略裁决，**不执行**。供 orchestrator 在 POLICY_CHECKED 分支用。

        闸1 注册校验、闸2 结构校验失败 → 合成 deny；通过则返回策略引擎的裁决。
        """
        return self._validate_tool_call(tool)

    async def call(self, tool: CandidateTool, *, approved: bool = False) -> CallOutcome:
        """tools/call：三道闸 → 执行 → 结果闸。任一闸不过则不执行。

        approved=True 仅放行经人工审批的 confirm；deny 永远拦死、allow 始终放行。
        gateway 是权威执行边界，即便 orchestrator 已先 evaluate 过，此处仍重新过闸
        （防御纵深；策略引擎须为确定性，两次裁决一致）。
        """
        # 闸1：注册校验（先单独取 spec——下面 config.diff 分支与执行都要用）
        spec = self._registry.get(tool.name)
        if spec is None:
            return CallOutcome(
                executed=False,
                verdict=_deny_verdict(f"unknown tool: {tool.name}"),
                reason="unregistered tool",
            )

        # 闸2+闸3：schema 校验 + 策略裁决（与内部快照调用共用同一实现，M-1）
        verdict = self._validate_tool_call(tool)
        if verdict.decision == "deny":
            # 区分 schema 失败与策略 deny 的 reason 口径（保持原有对外表述）
            reason = (
                verdict.reason
                if verdict.reason.startswith("schema validation failed")
                else "policy: deny"
            )
            return CallOutcome(executed=False, verdict=verdict, reason=reason)
        if verdict.decision == "confirm" and not approved:
            return CallOutcome(
                executed=False, verdict=verdict, reason="policy: confirm (needs approval)"
            )

        # config.diff：mcp 层聚合（决策⑤）。三道闸已过，但**不**落单命令特权执行器
        # （config.diff 无单命令模板→127）；改复用 config.hash_snapshot 取真快照后与基线对比。
        if spec.name == "config.diff":
            return await self._aggregate_config_diff(tool, verdict)

        # 执行 + 结果闸：密封不可信（强制 is_untrusted=True + 标准 wrap_token）
        result = await self._executor.execute(tool)
        result = seal_result(result)
        return CallOutcome(executed=True, result=result, verdict=verdict)

    async def _aggregate_config_diff(
        self, tool: CandidateTool, verdict: PolicyVerdict
    ) -> CallOutcome:
        """config.diff mcp 层聚合：复用 config.hash_snapshot 取真快照 → 与基线对比 → ConfigDiff。

        决策⑤：聚合只在 mcp 层，**绝不**把 config.diff 交给单命令特权执行器（会 127）。
        config.hash_snapshot 经真 Executor（路径 canonicalize/沙箱照常）；快照失败（exit≠0）
        按方案 B 原样上抛该 ToolResult（密封后返回），不吞错、不伪造空 diff。
        """
        paths = tool.args.get("paths", [])
        snapshot_tool = CandidateTool(name="config.hash_snapshot", args={"paths": paths})
        # 之七十五 M-1：内部快照调用也过同一套校验（注册 + schema + 策略），
        # 不再直接 execute。paths 来自 tool.args（模型可控）；虽已随 config.diff
        # 过完策略闸与路径闸，但让内部构造的调用绕过闸链会埋下一致性缺口——
        # config.hash_snapshot 的 schema/策略日后收紧时，这条路径不会同步生效。
        # 仍不走 call()：会与决策⑤冲突并引入 call→aggregate→call 递归。
        snap_verdict = self._validate_tool_call(snapshot_tool)
        if snap_verdict.decision == "deny":
            reason = f"internal config.hash_snapshot rejected: {snap_verdict.reason}"
            return CallOutcome(executed=False, verdict=snap_verdict, reason=reason)

        snap = await self._executor.execute(snapshot_tool)
        if snap.exit_code != 0:
            # 方案 B：快照命令失败原样上抛（别吞错）；结果闸照常密封。
            return CallOutcome(
                executed=True,
                result=seal_result(snap),
                verdict=verdict,
                reason="config.hash_snapshot failed (exit!=0)",
            )

        current = parse_sha256sum_output(snap.stdout_truncated)
        key = config_diff.baseline_key(tool.args)
        diff, established = self._config_diff.compute(key, current)
        payload = config_diff.to_stdout(diff, baseline_established=established, key=key)
        result = ToolResult(
            tool="config.diff",
            args=tool.args,
            exit_code=0,
            stdout_truncated=payload,
            is_untrusted=True,
        )
        return CallOutcome(executed=True, result=seal_result(result), verdict=verdict)
