"""D2-b LLM 网关测试：解析/校验、重试纠错、降级、抗裸shell字段。

全部用注入的假 completion_fn，不触网；用 asyncio.run 跑协程，不引 pytest-asyncio。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.app.contracts.intent import Intent
from backend.app.llm.adapter import LLMAdapter, LLMConfig, parse_intent
from backend.app.llm.prompts import OBSERVE_ONLY_INTENT

_GOOD = {
    "intent": "clean_system_garbage",
    "confidence": 0.86,
    "need_observation": True,
    "candidate_tools": [{"name": "disk.large_files", "args": {"path": "/var/log"}}],
    "risk_hint": "medium",
    "justification": "根分区占用高",
}


def _fn_returning(*outputs: str):
    """构造按调用次序返回预设输出的假 completion_fn。"""
    seq = list(outputs)
    calls = {"n": 0}

    async def fn(messages):  # noqa: ANN001
        out = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return out

    fn.calls = calls  # type: ignore[attr-defined]
    return fn


def test_plan_success_first_try() -> None:
    adapter = LLMAdapter(completion_fn=_fn_returning(json.dumps(_GOOD)))
    intent = asyncio.run(adapter.plan([{"role": "user", "content": "清理垃圾"}]))
    assert isinstance(intent, Intent)
    assert intent.candidate_tools[0].name == "disk.large_files"


def test_plan_tolerates_code_fence() -> None:
    fenced = "```json\n" + json.dumps(_GOOD) + "\n```"
    adapter = LLMAdapter(completion_fn=_fn_returning(fenced))
    intent = asyncio.run(adapter.plan([{"role": "user", "content": "x"}]))
    assert intent.intent == "clean_system_garbage"


def test_plan_retries_then_succeeds() -> None:
    fn = _fn_returning("not json at all", json.dumps(_GOOD))
    adapter = LLMAdapter(completion_fn=fn)
    intent = asyncio.run(adapter.plan([{"role": "user", "content": "x"}]))
    assert intent.intent == "clean_system_garbage"
    assert fn.calls["n"] == 2  # 第一次坏 + 第二次纠错成功


def test_plan_degrades_after_exhausting_retries() -> None:
    fn = _fn_returning("garbage")
    adapter = LLMAdapter(config=LLMConfig(max_retries=2), completion_fn=fn)
    intent = asyncio.run(adapter.plan([{"role": "user", "content": "x"}]))
    assert intent == OBSERVE_ONLY_INTENT
    assert fn.calls["n"] == 3  # 1 首次 + 2 纠错


def test_plan_rejects_bare_shell_field() -> None:
    """LLM 偷渡裸 shell 字段 → extra=forbid 拒 → 重试用尽降级（铁律3/S3）。"""
    poisoned = json.dumps({**_GOOD, "shell": "rm -rf /"})
    fn = _fn_returning(poisoned)
    adapter = LLMAdapter(config=LLMConfig(max_retries=1), completion_fn=fn)
    intent = asyncio.run(adapter.plan([{"role": "user", "content": "x"}]))
    assert intent == OBSERVE_ONLY_INTENT


def test_parse_intent_raises_on_garbage() -> None:
    with pytest.raises(ValueError):
        parse_intent("definitely not json")
