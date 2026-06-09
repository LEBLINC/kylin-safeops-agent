"""契约 6：前端事件流 WS/SSE（手册 §1.3）。

orchestrator 推送 / 前端(X)订阅。
data 字段按 type 对应固定 schema；各 type 的 data 约定见下方注释，
后续随状态机细化在此补全（改动须走 contract: 单独 commit）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 事件类型，对应状态机各转移点 + 终态错误。
# data 约定（初版，后续细化）：
#   intent_parsed   -> {"intent": Intent}
#   observation     -> {"results": list[ToolResult]}
#   plan_generated  -> {"candidate_tools": list[CandidateTool]}
#   policy_verdict  -> {"verdict": PolicyVerdict, "per_tool": list[{tool, verdict}]}
#   await_approval  -> {"reason": str, "tools": list[{"tool": str, "approval_role": str|None}]}
#   executing       -> {"tools": list[str]}
#   tool_result     -> {"result": ToolResult}
#   verified        -> {"summary": str}
#   rca             -> {"report": dict}
#   audit_appended  -> {"seq": int, "curr_hash": str}
#   error           -> {"message": str, "phase": str}
EventType = Literal[
    "intent_parsed",
    "observation",
    "plan_generated",
    "policy_verdict",
    "await_approval",
    "executing",
    "tool_result",
    "verified",
    "rca",
    "audit_appended",
    "error",
]


class StreamEvent(BaseModel):
    """推送给前端的单个流式事件。"""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(..., description="单次请求的全链路追踪 id")
    type: EventType = Field(..., description="事件类型")
    ts: float = Field(..., description="事件时间戳（epoch 秒）")
    data: dict = Field(default_factory=dict, description="按 type 对应固定 schema")
