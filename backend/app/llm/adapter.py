"""LLM 网关 adapter（手册 §3.2）。

单一接口 ``async plan(messages) -> Intent``：调 OpenAI 兼容端点，把模型输出
解析/校验为契约2 的 Intent；校验失败则带错误信息重试纠错（最多 2 次），
仍失败则降级为"仅观测、不规划"(OBSERVE_ONLY_INTENT)。

安全定位（铁律 1/3）：LLM 是不可信顾问，本层只产出结构化 Intent，
绝不生成或执行裸 shell；裸 shell 字段会被 Intent(extra="forbid") 拦截。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TypeAlias

import httpx
from pydantic import ValidationError

from backend.app.contracts.intent import Intent
from backend.app.llm.prompts import (
    OBSERVE_ONLY_INTENT,
    build_repair_prompt,
    build_summary_prompt,
    build_system_prompt,
)

# 一条对话消息：{"role": "user"|"assistant"|"system", "content": "..."}。
Message: TypeAlias = dict[str, str]

# 可注入的补全函数：输入消息列表，返回模型的原始文本输出。
# 默认实现走 httpx + OpenAI 兼容 /chat/completions；测试可注入假函数避免联网。
CompletionFn: TypeAlias = Callable[[list[Message]], Awaitable[str]]

# 可注入的流式补全函数：输入消息列表，异步产出文本增量片段。
StreamFn: TypeAlias = Callable[[list[Message]], AsyncIterator[str]]


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


def _balanced_object_at(text: str, start: int) -> str | None:
    """从 text[start]（须为 '{'）起扫描出括号平衡的对象，尊重字符串与转义。

    返回该对象子串；括号未闭合返回 None。
    """
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None  # 括号未闭合（被截断）


def _first_balanced_object(text: str) -> str | None:
    """文本中第一个括号平衡的 JSON 对象（从首个 '{' 起）。找不到返回 None。"""
    start = text.find("{")
    if start == -1:
        return None
    return _balanced_object_at(text, start)


def _strip_trailing_commas(text: str) -> str:
    """移除对象/数组里的尾逗号（常见非法 JSON），尊重字符串字面量。"""
    out: list[str] = []
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            continue
        if ch == ",":
            j = i + 1
            while j < len(text) and text[j] in " \t\r\n":
                j += 1
            if j < len(text) and text[j] in "}]":
                continue
        out.append(ch)
    return "".join(out)


def _extract_json(raw: str) -> str:
    """从模型输出里抽出第一个括号平衡的 JSON 对象主体（容错预览用）。"""
    obj = _first_balanced_object(raw)
    return obj if obj is not None else raw.strip()


def _loads_lenient(candidate: str) -> dict:
    """严格 json.loads；失败则移除尾逗号再试。仍失败抛 JSONDecodeError。"""
    try:
        return json.loads(candidate)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return json.loads(_strip_trailing_commas(candidate))  # type: ignore[no-any-return]


def parse_intent(raw: str) -> Intent:
    """把模型原始文本解析+校验为 Intent；失败抛 ValidationError/ValueError。

    稳健策略：依次尝试文本中每个括号平衡的 {...} 块（跳过散文里的伪对象如
    "{ignored?}"），对每块做宽松解析(去尾逗号)，取**第一个能解析且通过 Intent 校验**的。
    全部失败抛错，由 plan() 的重试/降级兜底。
    """
    last_exc: Exception = ValueError("no JSON object found")
    pos = raw.find("{")
    while pos != -1:
        candidate = _balanced_object_at(raw, pos)
        if candidate is not None:
            try:
                return Intent.model_validate(_loads_lenient(candidate))
            except (ValidationError, ValueError) as exc:
                last_exc = exc
        pos = raw.find("{", pos + 1)
    raise last_exc


class LLMAdapter:
    """OpenAI 兼容 LLM 网关。

    completion_fn 可注入以便测试；默认用 httpx 调 chat/completions。
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        completion_fn: CompletionFn | None = None,
        stream_fn: StreamFn | None = None,
    ) -> None:
        self.config = config or LLMConfig()
        self._completion_fn = completion_fn or self._default_completion
        self._stream_fn = stream_fn or self._default_stream

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

    async def _default_stream(self, messages: list[Message]) -> AsyncIterator[str]:
        """默认流式实现：httpx 流式读 OpenAI 兼容 SSE，逐 delta 产出文本片段。"""
        headers = {"Content-Type": "application/json", **self.config.extra_headers}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        body = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:") :].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                        delta = chunk["choices"][0]["delta"].get("content")
                    except (ValueError, KeyError, IndexError):
                        continue
                    if delta:
                        yield str(delta)

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

    async def stream_summary(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        """流式产出过程性自然语言叙述，给前端思维链动画（手册 §3.2）。

        纯展示用途：不解析、不校验、不产工具调用，与 plan() 的安全决策完全解耦；
        即便此处被注入也无法触达执行（执行只认 plan() 的结构化 Intent + 策略放行）。
        """
        convo: list[Message] = [
            {"role": "system", "content": build_summary_prompt()},
            *list(messages),
        ]
        async for piece in self._stream_fn(convo):
            yield piece
