"""结果闸：工具执行结果回喂前的不可信密封（铁律4）。

唯一职责：把任何 ToolResult 归一为"已密封不可信"形态——
强制 is_untrusted=True 且 wrap_token=标准 UNTRUSTED_WRAP_TOKEN，
防止被注入攻陷或实现有缺陷的 Executor 返回 is_untrusted=False
或畸形/伪造的 wrap_token 来削弱回喂时的定界隔离。

放在 mcp 层（gateway 的直接依赖）；agent/orchestrator 经 gateway 拿到的结果
均已密封，无需各自重复处理。
"""

from __future__ import annotations

from backend.app.contracts.untrusted import UNTRUSTED_WRAP_TOKEN, ToolResult


def seal_result(result: ToolResult) -> ToolResult:
    """归一结果闸：强制 is_untrusted=True 且 wrap_token 为标准定界符。

    若已是密封形态则原样返回（避免无谓拷贝）；否则返回修正后的副本。
    """
    if result.is_untrusted and result.wrap_token == UNTRUSTED_WRAP_TOKEN:
        return result
    return result.model_copy(update={"is_untrusted": True, "wrap_token": UNTRUSTED_WRAP_TOKEN})
