"""RCA（Root Cause Analysis）编排接入点（手册 D15）。

L 只定义【接口/Protocol】+ stub 占位 + orchestrator 调起点；真实 RCA playbook
（证据采集模板、根因推断）归 X 的 mcp_servers/rca/，由 X 落地。

约定：
- 输入：执行后的不可信观测/结果列表（已经 gateway 结果闸密封）。
- 输出：rca report dict——空 dict 表示"无可报告/无根因"，非空则会被 orchestrator
  作为契约6 "rca" 事件 emit({"report": <dict>}) 推给前端。
- TODO(BLOCKED-ON-X)：X 在 mcp_servers/rca/ 实现真 RCA 编排器，签名与本 Protocol 对齐。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from backend.app.contracts.untrusted import ToolResult


@runtime_checkable
class RCAEngine(Protocol):
    """RCA 编排器接口（X 实现，本模块不实现）。

    输入：本次请求收集到的所有 ToolResult（含观测+执行结果，全部 is_untrusted=True）。
    输出：rca report dict；空 dict {} 表示无可报告（orchestrator 据此跳过 emit）。
    严禁返回中含可执行命令字符串/路径——RCA 只产报告，不执行。
    """

    def analyze(self, evidence: Sequence[ToolResult]) -> dict: ...


class NullRCA:
    """默认 stub：永远返回空报告。orchestrator 不注入 rca 时用此默认值。"""

    def analyze(self, evidence: Sequence[ToolResult]) -> dict:
        return {}
