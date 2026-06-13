"""MCP Gateway（手册 §3.3）。

tools/list 与 tools/call。tools/call 的执行**强制**经过三道闸，顺序不可调换：
  1. 注册校验：工具必须已注册（未注册即拒，防影子工具）。
  2. 结构校验：args 按 ToolSpec.input_schema 过 schema_validator（策略前第一道闸）。
  3. 策略放行：过 D 的 PolicyEngine；非 allow 一律不执行。
放行后才交注入的 Executor 执行；结果一律包成契约4 ToolResult(is_untrusted=True)。

特例：``config.diff`` 在三道闸通过后于 **mcp 层聚合**（决策⑤），不落 D 的单命令执行器——
复用 ``config.hash_snapshot`` 取真实快照后与基线对比（见 ``config_diff`` 模块），保 D 执行器
"单命令模板"纯粹。

本层不直接跑命令、不拼 shell（铁律2）；执行委托 Executor（D 实现）。
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
    """特权代理执行器接口（D 实现）。

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

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        """前两道闸 + 策略裁决，**不执行**。供 orchestrator 在 POLICY_CHECKED 分支用。

        闸1 注册校验、闸2 结构校验失败 → 合成 deny；通过则返回 D 策略引擎的裁决。
        """
        spec = self._registry.get(tool.name)
        if spec is None:
            return _deny_verdict(f"unknown tool: {tool.name}")
        sv = validate_args(tool.args, spec.input_schema)
        if not sv.ok:
            return _deny_verdict("schema validation failed: " + "; ".join(sv.errors))
        return self._policy.evaluate(tool)

    async def call(self, tool: CandidateTool, *, approved: bool = False) -> CallOutcome:
        """tools/call：三道闸 → 执行 → 结果闸。任一闸不过则不执行。

        approved=True 仅放行经人工审批的 confirm；deny 永远拦死、allow 始终放行。
        gateway 是权威执行边界，即便 orchestrator 已先 evaluate 过，此处仍重新过闸
        （防御纵深；策略引擎须为确定性，两次裁决一致）。
        """
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

        # 闸3：策略放行。deny 永拦；confirm 仅在已审批时放行；allow 放行。
        verdict = self._policy.evaluate(tool)
        if verdict.decision == "deny":
            return CallOutcome(executed=False, verdict=verdict, reason="policy: deny")
        if verdict.decision == "confirm" and not approved:
            return CallOutcome(
                executed=False, verdict=verdict, reason="policy: confirm (needs approval)"
            )

        # config.diff：mcp 层聚合（决策⑤）。三道闸已过，但**不**落 D 单命令执行器
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

        决策⑤：聚合只在 mcp 层，**绝不**把 config.diff 交给 D 单命令执行器（会 127）。
        config.hash_snapshot 经真 Executor（路径 canonicalize/沙箱照常）；快照失败（exit≠0）
        按方案 B 原样上抛该 ToolResult（密封后返回），不吞错、不伪造空 diff。
        """
        paths = tool.args.get("paths", [])
        snapshot_tool = CandidateTool(name="config.hash_snapshot", args={"paths": paths})
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
