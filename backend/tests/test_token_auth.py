"""全量端点认证（verify_token mode-aware）端到端验证。

覆盖：
- proxy 命门（用例内覆盖回 proxy + 设共享密钥，勿被 conftest dev 默认架空）：
  无签名头打 /api/chat、/api/system/overview、/api/tools/registry → 401（fail-closed）；
  合法反代签名头 → 正常（200）。
- dev 模式（conftest 默认）：上述端点无头 → 正常放行（既有 ~360 测试不破的证据）。
- verify_token 只认证不加角色门槛：proxy 下任意合法签名（含非 admin）即可访问只读端点。

注：conftest 默认 KYLIN_AUTH_MODE=dev；proxy 用例 monkeypatch 覆盖回 proxy + 设密钥。
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from backend.app.api.app import create_app, lifespan
from backend.app.api.auth import sign_identity

_SECRET = "test-token-auth-secret"


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _signed_headers(user: str, roles_csv: str, *, ts: int | None = None) -> dict[str, str]:
    """构造合法 proxy 反代签名头（参照 test_rbac_wiring）。"""
    timestamp = str(ts if ts is not None else int(time.time()))
    signature = sign_identity(user, roles_csv, timestamp, _SECRET)
    return {
        "X-Auth-User": user,
        "X-Auth-Roles": roles_csv,
        "X-Auth-Timestamp": timestamp,
        "X-Auth-Signature": signature,
    }


# ============================================================
# proxy 模式（命门：无身份 fail-closed 401）
# ============================================================


def test_proxy_chat_without_identity_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：无签名头 POST /api/chat → 401。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                rr = await client.post("/api/chat", json={"message": "看下系统"})
                assert rr.status_code == 401

    asyncio.run(scenario())


def test_proxy_overview_without_identity_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：无签名头 GET /api/system/overview → 401。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                rr = await client.get("/api/system/overview")
                assert rr.status_code == 401

    asyncio.run(scenario())


def test_proxy_tools_registry_without_identity_unauthorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """proxy：无签名头 GET /api/tools/registry → 401。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                rr = await client.get("/api/tools/registry")
                assert rr.status_code == 401

    asyncio.run(scenario())


def test_proxy_signed_identity_allows_overview(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：合法反代签名头 → GET /api/system/overview 200。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                rr = await client.get(
                    "/api/system/overview", headers=_signed_headers("alice", "operator")
                )
                assert rr.status_code == 200

    asyncio.run(scenario())


def test_proxy_signed_identity_allows_tools_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：合法反代签名头 → GET /api/tools/registry 200。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                rr = await client.get(
                    "/api/tools/registry", headers=_signed_headers("alice", "operator")
                )
                assert rr.status_code == 200
                assert len(rr.json()) >= 1

    asyncio.run(scenario())


def test_proxy_signed_identity_allows_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：合法反代签名头 → POST /api/chat 200（拿到 trace_id）。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                rr = await client.post(
                    "/api/chat",
                    headers=_signed_headers("alice", "operator"),
                    json={"message": "看下系统"},
                )
                assert rr.status_code == 200
                assert "trace_id" in rr.json()

    asyncio.run(scenario())


def test_proxy_verify_token_authenticates_without_role_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """verify_token 只认证不加角色门槛：proxy 下任意合法签名（非 admin）即可访问只读端点。

    （角色授权归审批闸 can_approve，不在 verify_token 设角色限制。）
    """
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                # 一个低权角色（viewer）也能过 verify_token（只认证）
                rr = await client.get(
                    "/api/system/overview", headers=_signed_headers("carol", "viewer")
                )
                assert rr.status_code == 200

    asyncio.run(scenario())


def test_proxy_invalid_signature_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：篡改签名 → 401（fail-closed）。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                headers = _signed_headers("alice", "operator")
                headers["X-Auth-Signature"] = "deadbeef" * 8  # 篡改
                rr = await client.get("/api/system/overview", headers=headers)
                assert rr.status_code == 401

    asyncio.run(scenario())


# ============================================================
# dev 模式（conftest 默认：无头放行，既有测试不破的证据）
# ============================================================


def test_dev_mode_endpoints_allow_without_identity() -> None:
    """dev（conftest 默认）：无签名头打只读端点 → 正常放行（200）。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                assert (await client.get("/api/system/overview")).status_code == 200
                assert (await client.get("/api/tools/registry")).status_code == 200
                assert (
                    await client.post("/api/chat", json={"message": "看下系统"})
                ).status_code == 200

    asyncio.run(scenario())
