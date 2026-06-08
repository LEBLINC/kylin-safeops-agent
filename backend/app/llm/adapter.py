"""LLM 网关 adapter（手册 §3.2）。

单一接口 ``async plan(messages) -> Intent``：调 OpenAI 兼容端点，把模型输出
解析/校验为契约2 的 Intent；校验失败则带错误信息重试纠错（最多 2 次），
仍失败则降级为"仅观测、不规划"(OBSERVE_ONLY_INTENT)。

安全定位（铁律 1/3）：LLM 是不可信顾问，本层只产出结构化 Intent，
绝不生成或执行裸 shell；裸 shell 字段会被 Intent(extra="forbid") 拦截。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TypeAlias

import httpx
from pydantic import ValidationError

from backend.app.contracts.intent import Intent
from backend.app.llm.prompts import (
    OBSERVE_ONLY_INTENT,
    build_repair_prompt,
    build_system_prompt,
)

# 一条对话消息：{"role": "user"|"assistant"|"system", "content": "..."}。
Message: TypeAlias = dict[str, str]

# 可注入的补全函数：输入消息列表，返回模型的原始文本输出。
# 默认实现走 httpx + OpenAI 兼容 /chat/completions；测试可注入假函数避免联网。
CompletionFn: TypeAlias = Callable[[list[Message]], Awaitable[str]]


@dataclass
class LLMConfig:
    """LLM 网关配置（手册 §3.2：provider/base_url/model/timeout/temperature/max_tokens）。"""

    base_url: str = "http://localhost:8000/v1"
    model: str = "qwen2.5"
    api_key: str = ""
    timeout: float = 30.0
    temperature: float = 0.1
    max_tokens: int = 1024
    max_retries: int = 2  # schema 校验失败后的纠错重试次数上限
    provider: str = "openai_compatible"
    extra_headers: dict[str, str] = field(default_factory=dict)


def _extract_json(raw: str) -> str:
    """从模型输出里抽出 JSON 对象主体。

    容忍模型偶发包裹 ```json fence 或前后空白；不做语义修复，仅定位首尾花括号。
    """
    text = raw.strip()
    if text.startswith("```"):
        # 去掉可能的 ```json ... ``` 围栏
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.startswith("json"):
            text = text[len("json") :]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def parse_intent(raw: str) -> Intent:
    """把模型原始文本解析+校验为 Intent；失败抛 ValidationError/ValueError。"""
    payload = json.loads(_extract_json(raw))
    return Intent.model_validate(payload)


class LLMAdapter:
    """OpenAI 兼容 LLM 网关。

    completion_fn 可注入以便测试；默认用 httpx 调 chat/completions。
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        completion_fn: CompletionFn | None = None,
    ) -> None:
        self.config = config or LLMConfig()
        self._completion_fn = completion_fn or self._default_completion

    async def _default_completion(self, messages: list[Message]) -> str:
        """默认补全实现：httpx 调 OpenAI 兼容 /chat/completions。"""
        headers = {"Content-Type": "application/json", **self.config.extra_headers}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        body = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return str(data["choices"][0]["message"]["content"])

    async def plan(self, messages: Sequence[Message]) -> Intent:
        """规划主接口：返回合法 Intent；校验失败重试纠错，仍失败则降级仅观测。

        不抛网络以外的异常给调用方：解析/校验问题在内部消化为重试或降级，
        让 orchestrator 始终拿到一个可空跑的 Intent。
        """
        convo: list[Message] = [
            {"role": "system", "content": build_system_prompt()},
            *list(messages),
        ]
        last_error = ""
        # 首次 + max_retries 次纠错
        for attempt in range(self.config.max_retries + 1):
            raw = await self._completion_fn(convo)
            try:
                return parse_intent(raw)
            except (ValidationError, ValueError, KeyError) as exc:
                last_error = str(exc)
                if attempt == self.config.max_retries:
                    break
                # 把坏输出 + 错误回喂，要求模型自修
                convo = [
                    {"role": "system", "content": build_system_prompt()},
                    *list(messages),
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": build_repair_prompt(raw, last_error)},
                ]
        # 重试用尽仍不合法 → 降级为仅观测、不规划
        return OBSERVE_ONLY_INTENT.model_copy(deep=True)
