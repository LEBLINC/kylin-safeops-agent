"""GET /api/auth/whoami — 当前已验证身份端点单元测试。

覆盖：
- proxy 命门：合法签名头 → 200 + 正确 user/roles/mode=proxy；
  无签名头 → 401（verify_token fail-closed）；篡改签名 → 401。
- dev 模式（conftest 默认）：无头 → 200 + user="dev"/mode=dev/roles=[]；
  有 X-User-Role → roles=[role]。
- 只认证不加角色门槛：低权签名(viewer)亦可。
- 端点在 /api/auth/whoami（路由注册确认）。
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from backend.app.api.app import create_app, lifespan
from backend.app.api.auth import sign_identity

_SECRET = "test-whoami-secret"


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _signed_headers(user: str, roles_csv: str, *, ts: int | None = None) -> dict[str, str]:
    timestamp = str(ts if ts is not None else int(time.time()))
    sig = sign_identity(user, roles_csv, timestamp, _SECRET)
    return {
        "X-Auth-User": user,
        "X-Auth-Roles": roles_csv,
        "X-Auth-Timestamp": timestamp,
        "X-Auth-Signature": sig,
    }


# ============================================================
# proxy 模式（命门）
# ============================================================


def test_proxy_whoami_valid_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：合法签名头 → 200 + 正确 user/roles/mode=proxy。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                rr = await client.get(
                    "/api/auth/whoami",
                    headers=_signed_headers("alice", "operator,admin"),
                )
                assert rr.status_code == 200
                data = rr.json()
                assert data["user"] == "alice"
                assert set(data["roles"]) == {"operator", "admin"}
                assert data["mode"] == "proxy"

    asyncio.run(scenario())


def test_proxy_whoami_no_headers_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：无签名头 → verify_token fail-closed 401。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                rr = await client.get("/api/auth/whoami")
                assert rr.status_code == 401

    asyncio.run(scenario())


def test_proxy_whoami_tampered_signature_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：篡改签名 → 401（fail-closed）。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                headers = _signed_headers("alice", "operator")
                headers["X-Auth-Signature"] = "bad" * 20
                rr = await client.get("/api/auth/whoami", headers=headers)
                assert rr.status_code == 401

    asyncio.run(scenario())


def test_proxy_whoami_low_privilege_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：低权角色(viewer)的合法签名也能过（只认证不加角色门槛）。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                rr = await client.get(
                    "/api/auth/whoami",
                    headers=_signed_headers("bob", "viewer"),
                )
                assert rr.status_code == 200
                assert rr.json()["roles"] == ["viewer"]
                assert rr.json()["mode"] == "proxy"

    asyncio.run(scenario())


# ============================================================
# dev 模式（conftest 默认）
# ============================================================


def test_dev_whoami_no_role_header() -> None:
    """dev（conftest 默认）：无头 → 200 + dev 身份 + 空 roles。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                rr = await client.get("/api/auth/whoami")
                assert rr.status_code == 200
                data = rr.json()
                assert data["user"] == "dev"
                assert data["roles"] == []
                assert data["mode"] == "dev"

    asyncio.run(scenario())


def test_dev_whoami_with_role_header() -> None:
    """dev：带裸 X-User-Role → roles 包含该角色。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                rr = await client.get("/api/auth/whoami", headers={"X-User-Role": "admin"})
                assert rr.status_code == 200
                data = rr.json()
                assert data["roles"] == ["admin"]
                assert data["mode"] == "dev"

    asyncio.run(scenario())
