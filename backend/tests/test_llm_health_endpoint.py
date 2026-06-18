"""GET /api/llm/health 端点回归（阶段5 收尾）。

覆盖：
- fixture 模式（默认）：GET /api/llm/health → 200, provider=fixture, api_key_configured=False。
- real 模式 + dummy key：api_key_configured=True，**response 文本绝不泄漏 "dummy"**（S9）。
- 端点**不发 httpx POST**：只读 RealLLMConfig，绝不实例化 RealLLMClient。
- proxy 模式认证：依赖 verify_token 走 fail-closed（conftest 默认 dev 放行）。
- 路由注册在 /api/llm/health。

C3 严守：只读 backend.app.llm.real_client（不修改其逻辑）；只动 routers/schemas/tests。
"""

from __future__ import annotations

import asyncio
import os
from unittest import mock

import httpx

from backend.app.api.app import create_app, lifespan


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def test_llm_health_fixture_mode_default() -> None:
    """fixture 默认：GET /api/llm/health → 200, provider=fixture, key 未配置。"""

    async def scenario() -> None:
        app = create_app()
        # 清空 env 确保走默认（fixture + 空 key）；KYLIN_LLM_* 没设。
        async with lifespan(app):
            async with _client(app) as c:
                r = await c.get("/api/llm/health")
        assert r.status_code == 200, f"期望 200，实际 {r.status_code} {r.text}"
        body = r.json()
        assert body["provider"] == "fixture", f"provider 期望 fixture，实际 {body}"
        assert (
            body["api_key_configured"] is False
        ), f"默认 key 空，api_key_configured 应 False：{body}"
        # 配置态字段都应有
        for k in ("model", "base_url", "rate_limit_per_minute", "token_cap", "status"):
            assert k in body, f"缺字段 {k}: {body}"
        assert body["status"] == "ok"

    asyncio.run(scenario())


def test_llm_health_real_mode_does_not_leak_api_key() -> None:
    """real 模式 + dummy key：api_key_configured=True，**response 文本绝不泄漏 "dummy"**（S9）。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as c:
                with mock.patch.dict(
                    os.environ,
                    {
                        "KYLIN_LLM_PROVIDER": "real",
                        "KYLIN_LLM_BASE_URL": "http://my-llm.internal/v1",
                        "KYLIN_LLM_API_KEY": "sk-dummy-SECRET-XYZ",
                        "KYLIN_LLM_MODEL": "qwen3-max",
                    },
                    clear=False,
                ):
                    r = await c.get("/api/llm/health")
        assert r.status_code == 200
        body = r.json()
        assert body["provider"] == "real"
        assert body["model"] == "qwen3-max"
        assert body["api_key_configured"] is True
        # base_url 非密钥可回显（任务口径）
        assert body["base_url"] == "http://my-llm.internal/v1"
        # S9 铁律：response 文本/任何位置绝不出现 key 明文
        raw = r.text
        assert "sk-dummy-SECRET-XYZ" not in raw, f"key 明文泄漏：{raw}"
        assert "SECRET-XYZ" not in raw, f"key 子串泄漏：{raw}"
        # 字段值是 bool 不是 str
        assert isinstance(body["api_key_configured"], bool)

    asyncio.run(scenario())


def test_llm_health_does_not_initialize_client_or_send_httpx() -> None:
    """health 端点**不发 httpx POST**：只读 RealLLMConfig，绝不实例化 RealLLMClient。

    防御：mock 掉 RealLLMClient.__init__ → 若端点不小心 new 出来会炸。
    """
    from backend.app.llm import real_client

    init_called = {"n": 0}

    real_orig_init = real_client.RealLLMClient.__init__

    def spy_init(self: object, config: object = None) -> None:  # noqa: ANN001
        init_called["n"] += 1
        return real_orig_init(self, config)  # type: ignore[arg-type]

    async def scenario() -> None:
        with mock.patch.object(real_client.RealLLMClient, "__init__", spy_init):
            app = create_app()
            async with lifespan(app):
                async with _client(app) as c:
                    r = await c.get("/api/llm/health")
        assert r.status_code == 200
        # health 端点绝不该实例化 RealLLMClient（会触发 _RateLimiter/_TokenCounter 等）
        assert (
            init_called["n"] == 0
        ), f"health 端点不应实例化 RealLLMClient，实际调了 {init_called['n']} 次"

    asyncio.run(scenario())


def test_llm_health_route_registered() -> None:
    """端点路由注册确认：/api/llm/health 在 api_router 内。"""
    from backend.app.api.routers import api_router

    paths = {r.path for r in api_router.routes}  # type: ignore[attr-defined]
    assert "/api/llm/health" in paths, f"路由未注册：/api/llm/health。已注册：{paths}"


def test_llm_health_dev_mode_no_proxy_signature_required() -> None:
    """dev 模式（conftest 默认）：不需要 X-Auth-* 签名头即可访问（联调放行）。

    proxy 模式 fail-closed 由 test_proxy_whoami_* 系列覆盖（同名 verify_token），
    本测试只验 dev 路径 /api/llm/health 联通。
    """

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as c:
                r = await c.get("/api/llm/health")
        assert r.status_code == 200, f"dev 模式应放行，实际 {r.status_code} {r.text}"
        assert (
            r.json()["provider"] == "fixture"
        )  # conftest 强制 KYLIN_AUTH_MODE=dev 但 KYLIN_LLM_PROVIDER 默认 fixture

    asyncio.run(scenario())
