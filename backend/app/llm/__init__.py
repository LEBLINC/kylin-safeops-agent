"""LLM 网关层（手册 §3.2）：把不可信模型输出收敛为契约2 的强类型 Intent。"""

from backend.app.llm.adapter import (
    CompletionFn,
    LLMAdapter,
    LLMConfig,
    Message,
    StreamFn,
    parse_intent,
)
from backend.app.llm.prompts import (
    OBSERVE_ONLY_INTENT,
    build_repair_prompt,
    build_summary_prompt,
    build_system_prompt,
)

__all__ = [
    "CompletionFn",
    "LLMAdapter",
    "LLMConfig",
    "Message",
    "StreamFn",
    "parse_intent",
    "OBSERVE_ONLY_INTENT",
    "build_repair_prompt",
    "build_summary_prompt",
    "build_system_prompt",
]
