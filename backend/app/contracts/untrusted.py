"""契约 4：工具输出"不可信"标记（手册 §1.3）。

结果闸产出 / 回喂 LLM 前必经。抗注入关键：凡含外部数据一律标记 is_untrusted=True，
回喂时用 wrap_token 定界符包裹，使 LLM 不把工具输出当作可信指令执行。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: 回喂 LLM 时包裹不可信工具输出的定界 token。
UNTRUSTED_WRAP_TOKEN = "<<UNTRUSTED_TOOL_OUTPUT>>"


class ToolResult(BaseModel):
    """单次工具执行结果，默认标记为不可信。"""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(..., description="执行的工具名")
    args: dict = Field(default_factory=dict, description="实际调用参数")
    exit_code: int = Field(..., description="执行退出码")
    stdout_truncated: str = Field(..., description="已截断的标准输出")
    is_untrusted: bool = Field(default=True, description="默认 True：凡含外部数据一律标记为不可信")
    wrap_token: str = Field(default=UNTRUSTED_WRAP_TOKEN, description="回喂时用的定界符")
