"""L 域步骤 2：真 LLM 客户端测试。

覆盖：
- 不联网测试桩（fixture，默认）：5 类关键词 + D-10 注入样本 + 间接注入样本
- rate limit / token cap
- 真端点 httpx 调用（用 mock，不触网）
- S3 schema 校验失败：plan 走 retry → 仍失败 → 拒
- /api/llm/health 端点
- D-10 真 LLM 下 input_gate 仍拦 high（间接验）
- 间接注入（日志投毒）：result_gate is_untrusted OR policy_deny 任一即合规
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest import mock

import pytest

from backend.app.llm.real_client import (
    RealLLMClient,
    RealLLMConfig,
    _fixture_intent_for_message,
    load_real_llm_config_from_env,
)

# ---- 1. fixture 关键词解析 -------------------------------------------------


def test_fixture_intent_restart_sshd_parses_service_name() -> None:
    intent = json.loads(_fixture_intent_for_message("重启 sshd"))
    assert intent["candidate_tools"][0]["name"] == "service.restart"
    assert intent["candidate_tools"][0]["args"]["service_name"] == "sshd.service"


def test_fixture_intent_compress_path_parses_path() -> None:
    intent = json.loads(_fixture_intent_for_message("压缩 /var/log/app.log"))
    assert intent["candidate_tools"][0]["name"] == "log.compress_rotate"
    assert intent["candidate_tools"][0]["args"]["path"] == "/var/log/app.log"


def test_fixture_intent_unknown_falls_back_to_system_info() -> None:
    intent = json.loads(_fixture_intent_for_message("天气不错"))
    assert intent["candidate_tools"][0]["name"] == "system.info"


def test_fixture_intent_disk_usage() -> None:
    intent = json.loads(_fixture_intent_for_message("查看磁盘"))
    assert intent["candidate_tools"][0]["name"] == "disk.usage"


def test_fixture_intent_lsof_path() -> None:
    intent = json.loads(_fixture_intent_for_message("查 /etc/shadow"))
    assert intent["candidate_tools"][0]["name"] == "file.lsof_check"
    assert intent["candidate_tools"][0]["args"]["path"] == "/etc/shadow"


# ---- 2. ★D-10 注入样本（fixture 输出含注入 payload）-------------------------


def test_fixture_indirect_injection_via_syslog() -> None:
    """★间接注入样本：fixture 模拟"被 syslog 投毒诱导"，返回含 rm -rf / 的 Intent。

    测试期望：fixture 输出含投毒 payload，验证地板可拦——下游测试在 test_orchestrator
    上跑端到端验"策略闸 deny"或"结果闸 is_untrusted 包裹"任一即合规。
    """
    intent = json.loads(_fixture_intent_for_message("先看 /var/log/syslog 决定如何压缩"))
    # fixture 投毒 payload 在 args._poisoned_note（间接注入特征）
    args = intent["candidate_tools"][0]["args"]
    assert "rm -rf" in args.get(
        "_poisoned_note", ""
    ), f"间接注入 fixture 应含 rm -rf 投毒 payload，实际 {args!r}"


# ---- 3. rate limit / token cap ---------------------------------------------


def test_rate_limiter_blocks_after_max_per_minute() -> None:
    """N+1 次调用应 raise RuntimeError。"""
    from backend.app.llm.real_client import _RateLimiter

    async def scenario() -> None:
        limiter = _RateLimiter(max_per_minute=2)
        await limiter.acquire()
        await limiter.acquire()
        with pytest.raises(RuntimeError, match="rate limit exceeded"):
            await limiter.acquire()

    asyncio.run(scenario())


def test_token_cap_blocks_when_exceeded() -> None:
    """累计 token > cap 应 raise。"""
    from backend.app.llm.real_client import _TokenCounter

    counter = _TokenCounter(cap=10)
    counter.add("短文本")  # 6 chars / 4 = 1 token
    with pytest.raises(RuntimeError, match="token cap exceeded"):
        counter.add("一段" * 100)  # 200 chars / 4 = 50 tokens > 10 → 立即 raise
    with pytest.raises(RuntimeError, match="token cap exceeded"):
        counter.add("再一段" * 100)  # 继续 raise（幂等）


# ---- 4. env 装配 -----------------------------------------------------------


def test_load_real_llm_config_from_env_defaults() -> None:
    """默认 = fixture 模式（CI 友好）。"""
    env = {
        "KYLIN_LLM_PROVIDER": "",
        "KYLIN_LLM_BASE_URL": "",
        "KYLIN_LLM_MODEL": "",
        "KYLIN_LLM_API_KEY": "",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = load_real_llm_config_from_env()
    assert cfg.provider == "fixture"
    assert cfg.model == "qwen2.5"


def test_load_real_llm_config_from_env_real() -> None:
    """KYLIN_LLM_PROVIDER=real → 切真端点（env 注入 base_url/api_key）。"""
    env = {
        "KYLIN_LLM_PROVIDER": "real",
        "KYLIN_LLM_BASE_URL": "http://my-llm.internal/v1",
        "KYLIN_LLM_API_KEY": "sk-test-xxx",
        "KYLIN_LLM_MODEL": "qwen2.5-72b",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = load_real_llm_config_from_env()
    assert cfg.provider == "real"
    assert cfg.base_url == "http://my-llm.internal/v1"
    assert cfg.api_key == "sk-test-xxx"  # 走 env，不入库
    assert cfg.model == "qwen2.5-72b"


# ---- 5. S3 schema 校验失败 → 拒（D2-b LLMAdapter.plan 重试）--------------


def test_plan_rejects_after_schema_retry_exhausted() -> None:
    """completion_fn 永远返非 JSON → plan 拒（不抛到前端）。"""
    from backend.app.contracts.intent import Intent
    from backend.app.llm.adapter import LLMAdapter, LLMConfig

    config = LLMConfig(model="test", max_retries=2)
    call_count = {"n": 0}

    async def bad_completion(messages: list[dict[str, str]]) -> str:
        call_count["n"] += 1
        return "这不是 JSON"  # 永远 parse 失败

    adapter = LLMAdapter(
        config=config,
        completion_fn=bad_completion,
    )

    async def scenario() -> Intent:
        return await adapter.plan(
            messages=[{"role": "user", "content": "重启 cron"}],
        )

    intent = asyncio.run(scenario())
    # S3 schema 校验失败后降级 → OBSERVE_ONLY_INTENT（candidate_tools=[]）
    assert intent.candidate_tools == []
    assert call_count["n"] >= 2, f"应至少 retry 一次，实际 {call_count['n']}"


# ---- 6. 真端点 httpx 调用（mock，不触网）------------------------------------


def test_real_llm_completion_calls_openai_compatible_endpoint() -> None:
    """真端点模式：completion 走 httpx POST /chat/completions（mock 不触网）。"""

    def mock_response_setup() -> mock.MagicMock:
        r = mock.MagicMock()
        r.raise_for_status = mock.MagicMock()
        r.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        return r

    async def scenario() -> str:
        cfg = RealLLMConfig(
            provider="real",
            base_url="http://mock-llm/v1",
            api_key="sk-test",
            model="qwen2.5",
        )
        client = RealLLMClient(cfg)
        # 手动注入 mock http client（绕开 lazy init，避开 None.patch 错误）
        mock_http = mock.MagicMock()
        mock_http.post = mock.AsyncMock(return_value=mock_response_setup())
        mock_http.aclose = mock.AsyncMock()  # 显式 AsyncMock
        client._http = mock_http

        result = await client.completion_fn([{"role": "user", "content": "hi"}])
        assert mock_http.post.called
        assert "/chat/completions" in mock_http.post.call_args.args[0]
        assert result == "ok"

    asyncio.run(scenario())


# ---- 7. health_check 端点 --------------------------------------------------


def test_real_llm_health_check_fixture_mode() -> None:
    async def scenario() -> None:
        cfg = RealLLMConfig(provider="fixture", model="qwen2.5")
        client = RealLLMClient(cfg)
        h = await client.health_check()
        assert h["status"] == "ok"
        assert h["mode"] == "fixture"

    asyncio.run(scenario())


def test_real_llm_health_check_real_mode() -> None:
    async def scenario() -> None:
        cfg = RealLLMConfig(provider="real", base_url="http://my-llm/v1", model="qwen2.5")
        client = RealLLMClient(cfg)
        h = await client.health_check()
        assert h["status"] == "ok"
        assert h["mode"] == "real"
        assert h["base_url"] == "http://my-llm/v1"

    asyncio.run(scenario())
