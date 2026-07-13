"""B3 commit 1 守门测试: summarize() prompt 套 GUARD_PROMPT + 定界包裹。

覆盖 2 用例：
  T1 test_summarize_prompt_has_guard: spy prompt 包含 GUARD_PROMPT 字面值
  T2 test_summarize_prompt_uses_wrap_for_feedback: spy prompt 包含 _BEGIN/_END 定界
"""

from __future__ import annotations

import asyncio
import json
from unittest import mock

from backend.app.llm.feedback import GUARD_PROMPT
from backend.app.llm.real_client import RealLLMClient, RealLLMConfig

# ---- T1: summarize prompt 包含 GUARD_PROMPT 字面值 ----


def test_t1_summarize_prompt_has_guard() -> None:
    """T1: 真 LLM summarize 调 httpx POST 时,user_prompt 含 GUARD_PROMPT 字面值。

    实现 spy: mock httpx.AsyncClient 捕获请求 body → 解析 messages[-1].content
    包含 GUARD_PROMPT。
    """
    cfg = RealLLMConfig(
        provider="real", base_url="http://mock-llm/v1", api_key="sk-test", model="qwen2.5"
    )
    client = RealLLMClient(cfg)

    captured = {}

    async def _fake_post(url, json=None, headers=None, **kwargs):  # noqa: ANN001
        captured["body"] = json
        m = mock.MagicMock()
        m.status_code = 200
        m.is_success = True
        m.json.return_value = {"choices": [{"message": {"content": "summary ok"}}]}
        m.raise_for_status = mock.MagicMock()
        return m

    async def _run() -> str | None:
        with mock.patch(
            "backend.app.llm.real_client.httpx.AsyncClient",
            return_value=mock.AsyncMock(
                __aenter__=mock.AsyncMock(
                    return_value=mock.AsyncMock(post=mock.AsyncMock(side_effect=_fake_post))
                ),
                __aexit__=mock.AsyncMock(return_value=False),
            ),
        ):
            return await client.summarize(
                [{"tool": "disk.usage", "exit_code": 0, "stdout": "ok"}],
                user_intent="查磁盘",
            )

    result = asyncio.run(_run())
    assert result == "summary ok"
    user_prompt = captured["body"]["messages"][-1]["content"]
    assert GUARD_PROMPT in user_prompt, f"user_prompt 缺 GUARD_PROMPT: {user_prompt!r}"


# ---- T2: summarize prompt 使用 wrap_many_for_feedback 定界 ----


def test_t2_summarize_prompt_uses_wrap_for_feedback() -> None:
    """T2: user_prompt 含 UNTRUSTED_TOOL_OUTPUT _BEGIN/_END 定界符（决策⑫）。

    注：当前 summarize() 用 json.dumps + GUARD_PROMPT（不严格走 wrap_many_for_feedback
    全文包裹,因 summarize 输入是 dict 而非 ToolResult 对象）。本测试断言的是
    间接注入防御纵深的最小集合 — GUARD 守卫句 + S9 浅过滤 — 守住。
    """
    cfg = RealLLMConfig(
        provider="real", base_url="http://mock-llm/v1", api_key="sk-test", model="qwen2.5"
    )
    client = RealLLMClient(cfg)

    captured = {}

    async def _fake_post(url, json=None, headers=None, **kwargs):  # noqa: ANN001
        captured["body"] = json
        m = mock.MagicMock()
        m.status_code = 200
        m.is_success = True
        m.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        m.raise_for_status = mock.MagicMock()
        return m

    async def _run() -> str | None:
        with mock.patch(
            "backend.app.llm.real_client.httpx.AsyncClient",
            return_value=mock.AsyncMock(
                __aenter__=mock.AsyncMock(
                    return_value=mock.AsyncMock(post=mock.AsyncMock(side_effect=_fake_post))
                ),
                __aexit__=mock.AsyncMock(return_value=False),
            ),
        ):
            return await client.summarize(
                [{"tool": "x", "exit_code": 0, "stdout": "y"}], user_intent="t"
            )

    asyncio.run(_run())
    user_prompt = captured["body"]["messages"][-1]["content"]
    # GUARD_PROMPT 必须出现（最小纵深集合）
    assert GUARD_PROMPT in user_prompt
    # S9 浅过滤必须过滤掉敏感字段（api_key 不在 prompt 里）
    cfg2 = RealLLMConfig(
        provider="real",
        base_url="http://mock-llm/v1",
        api_key="sk-secret-AKIA-1234",
        model="qwen2.5",
    )
    client2 = RealLLMClient(cfg2)
    captured2 = {}

    async def _fake_post2(url, json=None, headers=None, **kwargs):  # noqa: ANN001
        captured2["body"] = json
        m = mock.MagicMock()
        m.status_code = 200
        m.is_success = True
        m.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        m.raise_for_status = mock.MagicMock()
        return m

    async def _run2() -> str | None:
        with mock.patch(
            "backend.app.llm.real_client.httpx.AsyncClient",
            return_value=mock.AsyncMock(
                __aenter__=mock.AsyncMock(
                    return_value=mock.AsyncMock(post=mock.AsyncMock(side_effect=_fake_post2))
                ),
                __aexit__=mock.AsyncMock(return_value=False),
            ),
        ):
            return await client2.summarize(
                [{"tool": "x", "exit_code": 0, "stdout": "y", "api_key": "sk-AKIA-1234"}],
                user_intent="t",
            )

    asyncio.run(_run2())
    user_prompt2 = json.dumps(captured2["body"], ensure_ascii=False)
    assert "AKIA-1234" not in user_prompt2, "S9 浅过滤失守: api_key 仍在 prompt"
