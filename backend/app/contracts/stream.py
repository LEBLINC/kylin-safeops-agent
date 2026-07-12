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
#   rejected        -> {"reason": str, "cause": str, "denied_tools": list}
#                       cause ∈ "injection" | "policy_deny" | "user_reject"
#   rca             -> {"report": dict}
#   natural_language -> {"text": str, "sensitive_filtered": bool}
#                       自然语言总结（验证后 LLM 调 tool_results 生成，仅前端聊天区展示）。
#                       text 由真 LLM/fake 产出；sensitive_filtered=True 表示 LLM 调前 S9 浅过滤已 REDACTED 敏感字段。
#                       间接注入防御纵深（决策⑫扩展接口）只 audit 拦下 emit 跳过；前端从不可信 SSE 收不到未审自然语言。
#                       S3：natural_language 不进 audit 哈希链，仅经 SSE 流式推送（前端聊天区）。
#   audit_appended  -> {"seq": int, "curr_hash": str}
#   error           -> {"message": str, "phase": str}
# 注：rejected 是 REJECTED 终态的显式结论事件（L-6 方案B）——三条 REJECTED 路径
#     （输入闸注入检测 high→deny / 策略 deny / 用户拒批）在关流前各 emit 一次，让前端及
#     任意 SSE 消费者能收尾出结论，不再依赖"回看历史状态推断"。
#     cause：injection=D-10 输入闸提示注入(high)；policy_deny=策略闸拒绝；user_reject=人工拒批。
EventType = Literal[
    "intent_parsed",
    "observation",
    "plan_generated",
    "policy_verdict",
    "await_approval",
    "executing",
    "tool_result",
    "verified",
    "rejected",
    "rca",
    "natural_language",
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
