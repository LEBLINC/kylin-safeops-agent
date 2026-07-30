"""决策⑤ — config.diff 在 mcp 层聚合（接回 registry + gateway 聚合，不落 D 执行器）。

覆盖：
- 聚合器单元：首次建基线（空 diff）、检出 changed、added/removed、baseline_key 区分。
- gateway 端到端（注入罐头 config.hash_snapshot 执行器）：首次建基线 → 改 hash 后返 changed；
  返回 ConfigDiff JSON + 结果闸密封（is_untrusted=True + 标准 wrap_token）；
  **executor 只见 config.hash_snapshot、从不见 config.diff**（决策⑤：永不落单命令特权执行器→127）。
- 快照失败（exit≠0）方案 B 原样上抛、不吞错。
- config.diff 仍走三道闸：schema 非法（空 paths）→ deny、executor 从未被调。
- build_gateway registry 含 config.diff（摘除恢复证据）。
"""

from __future__ import annotations

import asyncio
import json

from backend.app.api._fakes import FakePolicyEngine, build_gateway
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.untrusted import UNTRUSTED_WRAP_TOKEN, ToolResult
from backend.app.mcp.config_diff import ConfigDiffAggregator, baseline_key
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from mcp_servers.os_ops.parsers import parse_sha256sum_output
from mcp_servers.os_ops.tools_config import CONFIG_DIFF, CONFIG_HASH_SNAPSHOT

_HASH_A = "a" * 64
_HASH_B = "b" * 64


def _snap_stdout(mapping: dict[str, str]) -> str:
    """构造 sha256sum 输出：每行 '<64hex>  <path>'。"""
    return "".join(f"{h}  {p}\n" for p, h in mapping.items())


class _SeqExecutor:
    """注入桩：按调用顺序返回预置 config.hash_snapshot 结果；记录收到的工具名。"""

    def __init__(self, snaps: list[tuple[int, str]]) -> None:
        self.calls: list[str] = []
        self._snaps = list(snaps)

    async def execute(self, tool: CandidateTool) -> ToolResult:
        self.calls.append(tool.name)
        exit_code, stdout = self._snaps.pop(0)
        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=exit_code,
            stdout_truncated=stdout,
            is_untrusted=True,
        )


def _gateway(executor: _SeqExecutor) -> MCPGateway:
    registry = ToolRegistry([CONFIG_DIFF, CONFIG_HASH_SNAPSHOT])
    return MCPGateway(registry, FakePolicyEngine(), executor)  # type: ignore[arg-type]


# ============================================================
# 聚合器单元
# ============================================================


def test_aggregator_first_call_establishes_baseline() -> None:
    agg = ConfigDiffAggregator()
    snap = parse_sha256sum_output(_snap_stdout({"/etc/hosts": _HASH_A}))
    diff, established = agg.compute("k", snap)
    assert established is True
    assert (diff.added, diff.removed, diff.changed) == ([], [], [])


def test_aggregator_detects_change() -> None:
    agg = ConfigDiffAggregator()
    agg.compute("k", parse_sha256sum_output(_snap_stdout({"/etc/hosts": _HASH_A})))
    diff, established = agg.compute(
        "k", parse_sha256sum_output(_snap_stdout({"/etc/hosts": _HASH_B}))
    )
    assert established is False
    assert diff.changed == ["/etc/hosts"]
    assert diff.added == [] and diff.removed == []


def test_aggregator_added_and_removed() -> None:
    agg = ConfigDiffAggregator()
    agg.compute("k", parse_sha256sum_output(_snap_stdout({"/a.conf": _HASH_A})))
    diff, _ = agg.compute("k", parse_sha256sum_output(_snap_stdout({"/b.conf": _HASH_B})))
    assert diff.added == ["/b.conf"]
    assert diff.removed == ["/a.conf"]


def test_baseline_key_distinguishes_sources() -> None:
    assert baseline_key({"paths": ["/a"], "baseline_id": "x"}) == "id:x"
    # 无 baseline_id：按排序后 paths；不同 paths 集合互不串扰
    assert baseline_key({"paths": ["/b", "/a"]}) == "paths:/a,/b"
    assert baseline_key({"paths": ["/a"]}) != baseline_key({"paths": ["/b"]})


# ============================================================
# gateway 端到端聚合
# ============================================================


def test_gateway_config_diff_first_then_change() -> None:
    """首次建基线（空 diff）→ 改 hash 第二次返 changed；密封 + executor 只见 hash_snapshot。"""
    ex = _SeqExecutor(
        [
            (0, _snap_stdout({"/etc/hosts": _HASH_A})),
            (0, _snap_stdout({"/etc/hosts": _HASH_B})),
        ]
    )
    gw = _gateway(ex)

    async def scenario() -> None:
        tool = CandidateTool(name="config.diff", args={"paths": ["/etc/hosts"]})

        o1 = await gw.call(tool)
        assert o1.executed is True
        assert o1.result is not None
        assert o1.result.tool == "config.diff"
        # 结果闸密封（与其它工具一致）
        assert o1.result.is_untrusted is True
        assert o1.result.wrap_token == UNTRUSTED_WRAP_TOKEN
        p1 = json.loads(o1.result.stdout_truncated)
        assert p1["baseline_established"] is True
        assert p1["changed"] == []

        o2 = await gw.call(tool)
        assert o2.result is not None
        p2 = json.loads(o2.result.stdout_truncated)
        assert p2["baseline_established"] is False
        assert p2["changed"] == ["/etc/hosts"]

        # 决策⑤命门：executor 收到的全是 config.hash_snapshot，从不见 config.diff（不落 127）
        assert ex.calls == ["config.hash_snapshot", "config.hash_snapshot"]
        assert "config.diff" not in ex.calls

    asyncio.run(scenario())


def test_gateway_config_diff_snapshot_failure_passthrough() -> None:
    """方案 B：内部 config.hash_snapshot 失败（exit 127）→ 原样上抛、不吞错。"""
    ex = _SeqExecutor([(127, "sha256sum: not found")])
    gw = _gateway(ex)

    async def scenario() -> None:
        tool = CandidateTool(name="config.diff", args={"paths": ["/etc/hosts"]})
        o = await gw.call(tool)
        assert o.executed is True
        assert o.result is not None
        assert o.result.exit_code == 127
        assert o.result.is_untrusted is True  # 仍经结果闸密封
        assert ex.calls == ["config.hash_snapshot"]

    asyncio.run(scenario())


def test_gateway_config_diff_still_passes_gates_schema_deny() -> None:
    """config.diff 仍走三道闸：空 paths 违反 schema minItems → deny、executor 从未被调。"""
    ex = _SeqExecutor([])
    gw = _gateway(ex)

    async def scenario() -> None:
        tool = CandidateTool(name="config.diff", args={"paths": []})
        o = await gw.call(tool)
        assert o.executed is False
        assert o.verdict is not None
        assert o.verdict.decision == "deny"
        assert ex.calls == []  # 闸2 拦下，未触达执行器

    asyncio.run(scenario())


def test_build_gateway_registry_contains_config_diff() -> None:
    """摘除恢复证据：默认 build_gateway 的 registry 重新含 config.diff。"""
    names = {s.name for s in build_gateway().list_tools()}
    assert "config.diff" in names
    assert "config.hash_snapshot" in names
