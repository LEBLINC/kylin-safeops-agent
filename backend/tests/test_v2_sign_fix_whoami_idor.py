"""后端修复工单：v2 签名收尾 2 bug 守门（P1 实证抓到）。

Bug1（routers/auth.py::whoami）：proxy 模式下 whoami 只传 4 个 v1 字段调
verify_proxy_identity，_canonical 走 v1(3 字段)分支，与反代签的 v2(7 字段)串
不匹配 → 恒 401。修复：补 4 个 v2 字段（method/path/body_sha/nonce）。

Bug2（deps.py::principal_for_idor）：proxy 模式只从裸 X-User-Role 取 roles，
但反代已剥除该头 → principal.roles 恒空 → IDOR is_admin 恒 False（过严）；
审计 actor.roles 全空。修复：proxy 分支镜像 whoami/require_proxy_identity，
调 verify_proxy_identity 拿含 roles 的完整 Principal。

覆盖 2 用例（工单指定）：
  T1 proxy 模式 + 真 v2 签名头 → GET /api/auth/whoami 返 200 + roles 正确（非 401）
  T2 proxy 模式 + X-Auth-Roles=admin → principal_for_idor.roles 含 "admin"；
     chat IDOR admin 可续他人 session（roles 非空）
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time

import httpx
import pytest

_SECRET = "test-v2-sign-fix-secret"


def _sign_v2(
    user: str, roles: str, ts: str, method: str, path: str, body_sha: str, nonce: str
) -> str:
    """v2 签名（7 字段，与 deploy/proxy/proxy.py::sign / deps.py verify_token 同口径）。"""
    canonical = f"{user}\n{roles}\n{ts}\n{method}\n{path}\n{body_sha}\n{nonce}"
    return hmac.new(_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def _v2_headers(user: str, roles: str, method: str, path: str, nonce: str) -> dict[str, str]:
    ts = str(int(time.time()))
    body_sha = hashlib.sha256(b"").hexdigest()
    sig = _sign_v2(user, roles, ts, method, path, body_sha, nonce)
    return {
        "X-Auth-User": user,
        "X-Auth-Roles": roles,
        "X-Auth-Timestamp": ts,
        "X-Auth-Signature": sig,
        "X-Auth-Method": method,
        "X-Auth-Path": path,
        "X-Auth-Body-Sha": body_sha,
        "X-Auth-Nonce": nonce,
    }


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ============================================================
# Bug1: whoami v2 收尾
# ============================================================


def test_t1_whoami_v2_signature_returns_200_with_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    """T1: proxy 模式 + 真 v2 签名头 → GET /api/auth/whoami 返 200 + roles 正确（非 401）。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)
    from backend.app.api.app import create_app, lifespan

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                headers = _v2_headers(
                    "alice", "operator,admin", "GET", "/api/auth/whoami", "t1-nonce"
                )
                resp = await client.get("/api/auth/whoami", headers=headers)
                assert (
                    resp.status_code == 200
                ), f"T1: v2 签名应通过, got {resp.status_code}: {resp.text}"
                data = resp.json()
                assert data["user"] == "alice"
                assert set(data["roles"]) == {"operator", "admin"}
                assert data["mode"] == "proxy"

    asyncio.run(scenario())


# ============================================================
# Bug2: principal_for_idor roles 收尾
# ============================================================


def test_t2_principal_for_idor_roles_nonempty_admin_can_continue_others_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T2: proxy 模式 + X-Auth-Roles=admin → principal_for_idor.roles 含 "admin"；
    chat IDOR admin 可续他人 session（roles 非空）。
    """
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)
    from backend.app.api.deps import principal_for_idor

    async def _call_dep() -> None:
        headers = _v2_headers("bob-admin", "admin", "POST", "/api/chat", "t2-nonce")
        # 用真 Request 而非 MagicMock：P0-D1 后等值断言要读 scope["query_string"]，
        # MagicMock 的 .get() 返回 Mock 对象而非 bytes，会拼出错误 path 导致假红。
        from starlette.requests import Request as _Req

        async def _empty_receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        mock_req = _Req(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/chat",
                "query_string": b"",
                "headers": [],
            },
            receive=_empty_receive,
        )
        principal = await principal_for_idor(
            request=mock_req,
            x_auth_user=headers["X-Auth-User"],
            x_auth_roles=headers["X-Auth-Roles"],
            x_auth_timestamp=headers["X-Auth-Timestamp"],
            x_auth_signature=headers["X-Auth-Signature"],
            x_auth_method=headers["X-Auth-Method"],
            x_auth_path=headers["X-Auth-Path"],
            x_auth_body_sha=headers["X-Auth-Body-Sha"],
            x_auth_nonce=headers["X-Auth-Nonce"],
            x_user_role=None,
        )
        assert (
            "admin" in principal.roles
        ), f"T2: principal.roles 应含 admin, got {principal.roles!r}"
        assert principal.user == "bob-admin"
        return principal

    principal = asyncio.run(_call_dep())

    # 端到端：chat.py:79 的调用口径 is_admin="admin" in principal.roles——
    # 真从上一步拿到的 principal.roles 派生（非硬编码 True），才是真验证 Bug2 修复。
    from backend.app.api.session_store import SessionStore

    store = SessionStore()
    sess = store.create(title="alice-chat", owner="alice")
    is_admin = "admin" in principal.roles
    assert is_admin, "T2: roles 应非空才能推出 is_admin=True（Bug2 修复前 roles 恒空）"
    got = store.assert_owner(sess.session_id, "bob-admin", is_admin=is_admin)
    assert got.owner == "alice", "T2: admin 应能续他人 session"
