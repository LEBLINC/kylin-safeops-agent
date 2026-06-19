"""GET /api/llm/health?probe=true 探活端点测试（6 用例）。"""

from __future__ import annotations

import asyncio
from unittest import mock

import httpx
import pytest

from backend.app.api.app import create_app, lifespan


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ---- 1. 无 probe 参数 → 仅配置态，无 probe_* 字段 ---------------------


def test_health_no_probe_returns_base_fields() -> None:
    async def s() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as c:
                r = await c.get("/api/llm/health")
        assert r.status_code == 200
        body = r.json()
        assert "probe_status" not in body
        assert body["provider"] == "fixture"

    asyncio.run(s())


# ---- 2. ?probe=false → 等同无 probe ------------------------------------


def test_health_probe_false_returns_base_fields() -> None:
    async def s() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as c:
                r = await c.get("/api/llm/health?probe=false")
        assert r.status_code == 200
        assert "probe_status" not in r.json()

    asyncio.run(s())


# ---- 3. ?probe=true + fixture → probe_status="skipped" ----------------


def test_health_probe_fixture_skipped() -> None:
    async def s() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as c:
                r = await c.get("/api/llm/health?probe=true")
        assert r.status_code == 200
        body = r.json()
        assert body["probe_status"] == "skipped"
        assert body["probe_enabled"] is False
        assert body["probe_latency_ms"] is None

    asyncio.run(s())


# ---- 4. ?probe=true + real + 200 → probe_status="ok" -----------------


def test_health_probe_real_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KYLIN_LLM_PROVIDER", "real")
    monkeypatch.setenv("KYLIN_LLM_BASE_URL", "http://mock-llm/v1")
    monkeypatch.setenv("KYLIN_LLM_API_KEY", "sk-test")

    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True

    async def s() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as c:
                with mock.patch(
                    "backend.app.llm.real_client.httpx.AsyncClient",
                    return_value=mock.AsyncMock(
                        __aenter__=mock.AsyncMock(
                            return_value=mock.AsyncMock(post=mock.AsyncMock(return_value=mock_resp))
                        ),
                        __aexit__=mock.AsyncMock(return_value=False),
                    ),
                ):
                    r = await c.get("/api/llm/health?probe=true")
        assert r.status_code == 200
        body = r.json()
        assert body["probe_status"] == "ok"
        assert body["probe_enabled"] is True
        assert body["probe_latency_ms"] is not None
        assert body["probe_error"] is None

    asyncio.run(s())


# ---- 5. ?probe=true + real + 500 → probe_status="failed" + 不泄露原文 --


def test_health_probe_real_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KYLIN_LLM_PROVIDER", "real")
    monkeypatch.setenv("KYLIN_LLM_BASE_URL", "http://mock-llm/v1")
    monkeypatch.setenv("KYLIN_LLM_API_KEY", "sk-dummy-SECRET")

    mock_resp = mock.MagicMock()
    mock_resp.status_code = 500
    mock_resp.is_success = False

    async def s() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as c:
                with mock.patch(
                    "backend.app.llm.real_client.httpx.AsyncClient",
                    return_value=mock.AsyncMock(
                        __aenter__=mock.AsyncMock(
                            return_value=mock.AsyncMock(post=mock.AsyncMock(return_value=mock_resp))
                        ),
                        __aexit__=mock.AsyncMock(return_value=False),
                    ),
                ):
                    r = await c.get("/api/llm/health?probe=true")
        assert r.status_code == 200
        body = r.json()
        assert body["probe_status"] == "failed"
        # S9：不暴露 httpx 异常原文，只报 status_code
        assert "500" in body["probe_error"]
        # S9：不泄漏 api_key
        assert "sk-dummy-SECRET" not in r.text

    asyncio.run(s())


# ---- 6. ?probe=true + real + timeout → probe_status="timeout" ---------


def test_health_probe_real_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KYLIN_LLM_PROVIDER", "real")
    monkeypatch.setenv("KYLIN_LLM_BASE_URL", "http://mock-llm/v1")

    async def s() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as c:
                with mock.patch(
                    "backend.app.llm.real_client.httpx.AsyncClient",
                    return_value=mock.AsyncMock(
                        __aenter__=mock.AsyncMock(
                            return_value=mock.AsyncMock(
                                post=mock.AsyncMock(
                                    side_effect=httpx.ReadTimeout("timed out", request=None)
                                )
                            )
                        ),
                        __aexit__=mock.AsyncMock(return_value=False),
                    ),
                ):
                    r = await c.get("/api/llm/health?probe=true")
        assert r.status_code == 200
        assert r.json()["probe_status"] == "timeout"

    asyncio.run(s())
