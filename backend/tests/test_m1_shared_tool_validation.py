"""之七十五 M-1: config.diff 的内部快照调用复用同一套校验（闸链一致性）。

修前：_aggregate_config_diff 直接 self._executor.execute(snapshot_tool)，
绕过闸1 注册校验 / 闸2 schema 校验 / 闸3 策略裁决。paths 来自 tool.args（模型可控）。
该缺口的性质不是"当前可被利用"（config.diff 本身已过策略闸+路径闸，executor 内
仍 canonicalize），而是**闸链一致性缺口**：config.hash_snapshot 的 schema 或策略
日后一旦收紧，这条内部路径不会同步生效，收紧就是假的。

修法（工单已定案）：提取 _validate_tool_call(tool) -> PolicyVerdict 供 call() 与
内部快照调用共用。**刻意不复用 call()**——会与"聚合只在 mcp 层"（决策⑤）冲突，
并引入 call → _aggregate_config_diff → call 递归。

  M1-1 内部快照路径对策略 deny 同样被拒（不再绕闸）
  M1-2 config.diff 正常路径零回归（真快照 → 真 diff）
  M1-3 内部快照被拒时不执行任何命令（executor 未被调用）
  M1-4 evaluate() 与内部校验同源——同一 tool 得同一裁决（口径不分叉）
  M1-5 未引入递归：_aggregate_config_diff 不得调用 self.call
"""

from __future__ import annotations

import asyncio
import inspect

from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.untrusted import ToolResult
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from mcp_servers.os_ops.tools_config import CONFIG_DIFF, CONFIG_HASH_SNAPSHOT

_PATHS = ["/etc/hosts"]


def _verdict(decision: str) -> PolicyVerdict:
    return PolicyVerdict(
        decision=decision,  # type: ignore[arg-type]
        final_risk="R0",
        matched_rules=["rule.test"],
        reason=f"test {decision}",
        approval_required=False,
        approval_role=None,
    )


class _PerToolPolicy:
    """按工具名给不同裁决——用于制造"config.diff 放行、内部快照被拒"的场景。"""

    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping
        self.seen: list[str] = []

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        self.seen.append(tool.name)
        return _verdict(self.mapping.get(tool.name, "allow"))


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, tool: CandidateTool) -> ToolResult:
        self.calls.append(tool.name)
        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=0,
            stdout_truncated="d41d8cd98f00b204e9800998ecf8427e  /etc/hosts",
        )


def _gateway(policy_map: dict[str, str]):
    registry = ToolRegistry([CONFIG_DIFF, CONFIG_HASH_SNAPSHOT])
    policy = _PerToolPolicy(policy_map)
    executor = _RecordingExecutor()
    return MCPGateway(registry, policy, executor), policy, executor


def test_m1_1_internal_snapshot_respects_policy_deny() -> None:
    """M1-1: 内部快照调用被策略 deny → 整个 config.diff 不执行（不再绕闸）。"""
    gateway, _policy, executor = _gateway({"config.hash_snapshot": "deny"})

    outcome = asyncio.run(gateway.call(CandidateTool(name="config.diff", args={"paths": _PATHS})))

    assert outcome.executed is False, "M1-1: 内部快照被拒时不应报告已执行"
    assert "config.hash_snapshot" in (
        outcome.reason or ""
    ), f"M1-1: reason 应点明内部快照被拒，实际 {outcome.reason!r}"
    assert executor.calls == [], "M1-1: 被拒后不得执行任何命令"


def test_m1_2_normal_path_no_regression() -> None:
    """M1-2: 全 allow 时 config.diff 正常聚合（真快照 → 真 diff），零回归。"""
    gateway, _policy, executor = _gateway({})

    outcome = asyncio.run(gateway.call(CandidateTool(name="config.diff", args={"paths": _PATHS})))

    assert outcome.executed is True
    assert outcome.result is not None
    assert outcome.result.tool == "config.diff"
    assert executor.calls == [
        "config.hash_snapshot"
    ], f"M1-2: 应只经内部快照取真数据，实际 {executor.calls}"
    assert outcome.result.is_untrusted is True, "M1-2: 结果闸仍须密封"


def test_m1_3_internal_snapshot_schema_gate_active() -> None:
    """M1-3: 内部快照的 schema 校验真生效——非法 paths（相对路径）被拒。

    _PATHS_SCHEMA 要求 pattern ^/ ；相对路径应在闸2 被拦，且不触达 executor。
    """
    gateway, _policy, executor = _gateway({})

    # 绕过 config.diff 自身的 schema（直接验内部校验函数），确认同一套校验在生效
    verdict = gateway._validate_tool_call(
        CandidateTool(name="config.hash_snapshot", args={"paths": ["etc/passwd"]})
    )
    assert verdict.decision == "deny", "M1-3: 相对路径应被 schema 闸拒"
    assert "schema validation failed" in verdict.reason
    assert executor.calls == []


def test_m1_4_evaluate_and_internal_validation_same_source() -> None:
    """M1-4: evaluate() 与内部校验同源，同一 tool 必得同一裁决（口径不分叉）。"""
    gateway, _policy, _executor = _gateway({"config.hash_snapshot": "confirm"})
    tool = CandidateTool(name="config.hash_snapshot", args={"paths": _PATHS})

    assert gateway.evaluate(tool).decision == gateway._validate_tool_call(tool).decision


def test_m1_5_no_recursion_into_call() -> None:
    """M1-5: _aggregate_config_diff 不得调 self.call——否则 call→aggregate→call 递归。

    这是工单明确的边界（与决策⑤"聚合只在 mcp 层"冲突），故用源码断言钉死。
    """
    src = inspect.getsource(MCPGateway._aggregate_config_diff)
    assert "self.call(" not in src, "M1-5: 不得复用 call()（递归 + 违决策⑤）"
    assert "self._validate_tool_call(" in src, "M1-5: 应复用提取出的共用校验"
