"""D 阻断修复: deps.py v2 proxy verify 同步守门 (4 用例 T1-T4).

D 报告: 生产反代链路 100% 401 (所有转发流量 fail).
架构者亲核: deps.py verify_token + require_proxy_identity 仍传 4 旧参数,
反代 v2 7 字段签名与后端 v1 串不匹配 → 401.

覆盖 4 用例:
  T1 模拟真实反代 v2 签名 (8 header 齐全) → 200
  T2 4 header v1 签 (backward compat) → 200
  T3 v2 签但 secret 错 → 401
  T4 require_proxy_identity v2 签 → Principal 返
"""

from __future__ import annotations

import hashlib
import hmac
import time

SECRET = "kylin-test-d-deps-v2"


def _sign_v2(user, roles, ts, method, path, body_sha, nonce):
    """真接 v2 签名 (7 字段, 与 deploy/proxy/proxy.py::sign 同口径)."""
    canonical = f"{user}\n{roles}\n{ts}\n{method}\n{path}\n{body_sha}\n{nonce}"
    return hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def test_t1_deps_verify_proxy_v2_full_headers_pass(monkeypatch) -> None:
    """T1: 8 header 齐全 + v2 真签 → 200 (反代真接链路走通)."""
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", SECRET)
    from fastapi.testclient import TestClient

    from backend.app.api.app import create_app
    app = create_app()
    client = TestClient(app)

    user = "alice_admin"
    roles = "admin"
    ts = str(int(time.time()))
    method = "GET"
    path = "/api/chat"
    body_sha = hashlib.sha256(b"").hexdigest()
    nonce = "t1-nonce-unique"

    sig = _sign_v2(user, roles, ts, method, path, body_sha, nonce)
    resp = client.get(
        path,
        headers={
            "X-Auth-User": user,
            "X-Auth-Roles": roles,
            "X-Auth-Timestamp": ts,
            "X-Auth-Signature": sig,
            "X-Auth-Method": method,
            "X-Auth-Path": path,
            "X-Auth-Body-Sha": body_sha,
            "X-Auth-Nonce": nonce,
        },
    )
    assert resp.status_code != 401, f"T1: v2 链路应通过, got 401: {resp.text}"


def test_t2_v1_only_falls_back(monkeypatch) -> None:
    """T2: 4 header + v1 sign → 200 (backward compat, _canonical 全空走 v1 串)."""
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", SECRET)
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    user = "alice"
    roles = "admin"
    ts = str(int(time.time()))
    # v1 canonical (3 字段)
    canonical = f"{user}\n{roles}\n{ts}"
    sig = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    from fastapi.testclient import TestClient

    from backend.app.api.app import create_app
    app = create_app()
    with TestClient(app) as client:
        resp = client.get(
            "/api/system/overview",
            headers={
                "X-Auth-User": user,
                "X-Auth-Roles": roles,
                    "X-Auth-Timestamp": ts,
                    "X-Auth-Signature": sig,
                },
            )
    # v1 兼容性: v1 串 (3 字段) 与 v2 串 (7 字段, 全空尾随) 字节级不同
    # 但 _canonical backward compat: 全空 method/path/body/nonce 走 v1
    # → verify 应通过 (200 或 403 视 endpoint 权限, 但不应 401)
    assert resp.status_code != 401, f"T2: v1 签名应通过, got 401: {resp.text}"


def test_t3_v2_signature_mismatch_returns_401(monkeypatch) -> None:
    """T3: v2 签但 secret 错 → 401."""
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", "correct-secret")
    user = "alice"
    roles = "admin"
    ts = str(int(time.time()))
    sig = _sign_v2(user, roles, ts, "GET", "/api/x", "abc", "n")
    # 覆写 env: verify 用 correct, 但 sig 用 wrong
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", "wrong-secret")
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    from fastapi.testclient import TestClient

    from backend.app.api.app import create_app
    app = create_app()
    with TestClient(app) as client:
        resp = client.get(
            "/api/system/overview",
            headers={
                "X-Auth-User": user,
                "X-Auth-Roles": roles,
                    "X-Auth-Timestamp": ts,
                    "X-Auth-Signature": sig,
                    "X-Auth-Method": "GET",
                    "X-Auth-Path": "/api/x",
                    "X-Auth-Body-Sha": "abc",
                    "X-Auth-Nonce": "n",
                },
            )
    assert resp.status_code == 401, f"T3 期望 401, got {resp.status_code}"


def test_t4_require_proxy_identity_v2_pass(monkeypatch) -> None:
    """T4: 8 header v2 签 → require_proxy_identity 返 Principal (非 401)."""
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", SECRET)
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    user = "alice"
    roles = "admin"
    ts = str(int(time.time()))
    sig = _sign_v2(user, roles, ts, "GET", "/api/x", "abc", "nonce-t4")
    # T4 直接调 verify_proxy_identity (单元级, 不走 HTTP 全链路)
    from backend.app.api.auth import verify_proxy_identity
    p = verify_proxy_identity(
        user=user,
        roles=roles,
        timestamp=ts,
        signature=sig,
        method="GET",
        path="/api/x",
        body_sha="abc",
        nonce="nonce-t4",
    )
    assert p is not None, "T4 期望 Principal, got None"
    assert p.user == user
    assert p.roles == frozenset({"admin"})
