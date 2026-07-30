"""config.diff 的 mcp 层聚合（决策⑤：聚合在 mcp 层，不进 D 执行器）。

config.diff 无单命令模板（语义是"当前快照 × 基线对比"），故**不**落单命令特权执行器
（落进去会 127）。gateway.call 在三道闸通过后特判 config.diff，调本模块聚合：
复用 config.hash_snapshot（真单命令工具，经 Executor 做路径 canonicalize/沙箱）取当前快照
→ 与基线对比 → 返回结构化 ConfigDiff。决策⑤铁律：D 执行器保持"单命令模板"纯粹，聚合只在 mcp 层。

基线策略（v1 = 内存、gateway 实例级，诚实可逆）：
- 首次某 baseline key 无基线 → 建立基线、返回空 diff（baseline_established=True）；
- 后续调用 → 与上次快照对比返回 added/removed/changed，并把基线**滚动**为当前快照
  （即"距上次 config.diff 调用以来的漂移"）；
- **不跨进程/重启持久化**（gateway 实例级内存 dict，进程结束即丢）。
  跨重启持久化基线（env 可配路径 + 受限权限 + fail-safe）列 backlog，本单不做。

本模块只持基线状态 + 纯 diff/序列化；不触 Executor、不跑命令（执行委托 gateway 的 Executor）。
"""

from __future__ import annotations

import json

from mcp_servers.os_ops.models import ConfigDiff, ConfigSnapshot
from mcp_servers.os_ops.parsers import diff_config_snapshots

#: 既无 baseline_id 又无 paths 时的兜底 key（schema 已要求 paths，正常不会命中）。
_DEFAULT_KEY = "__default__"


def baseline_key(args: dict) -> str:
    """从 config.diff args 推导基线 key：优先显式 baseline_id，否则按排序后的 paths 集合。

    不同 paths 集合 / 不同 baseline_id 各自独立基线，互不串扰。
    """
    bid = args.get("baseline_id")
    if isinstance(bid, str) and bid.strip():
        return f"id:{bid.strip()}"
    paths = args.get("paths") or []
    if not paths:
        return _DEFAULT_KEY
    return "paths:" + ",".join(sorted(str(p) for p in paths))


class ConfigDiffAggregator:
    """config.diff 基线存取 + 漂移计算（gateway 实例级内存基线，v1）。"""

    def __init__(self) -> None:
        self._baselines: dict[str, ConfigSnapshot] = {}

    def compute(self, key: str, current: ConfigSnapshot) -> tuple[ConfigDiff, bool]:
        """对比并滚动基线。

        返回 (diff, baseline_established)：
        - 首次（key 无基线）：存基线、返回空 diff + established=True；
        - 后续：返回 diff(上次基线, current) + established=False；随后基线滚动为 current。
        """
        baseline = self._baselines.get(key)
        self._baselines[key] = current  # 基线滚动为当前快照
        if baseline is None:
            return ConfigDiff(), True
        return diff_config_snapshots(baseline, current), False


def to_stdout(diff: ConfigDiff, *, baseline_established: bool, key: str) -> str:
    """把聚合结果序列化为 config.diff 的 stdout（JSON）；经 seal_result 密封后回喂。

    baseline_established 诚实标注本次是否仅建立基线（首次调用 diff 必空）。
    """
    return json.dumps(
        {
            "added": diff.added,
            "removed": diff.removed,
            "changed": diff.changed,
            "baseline_established": baseline_established,
            "baseline_key": key,
        }
    )
