"""测试全局夹具（pytest 自动发现）。

测试卫生（审阅决策③派生）：app lifespan 默认把审计库落 ./data/audit.db（真文件，跨运行累积、
污染工作树）。本 autouse 夹具把 `_AUDIT_DB_PATH` 指向 :memory:，使任何经 lifespan 的测试都用
内存审计库，杜绝在工作树落地 audit.db。需真文件库的测试可在用例内再行覆盖。

认证模式（接线增量·任务甲）：生产默认 `KYLIN_AUTH_MODE=proxy`（强制反代签名身份，fail-closed）。
为不切断大量经 `X-User-Role` 驱动审批续跑的既有/联调测试，本夹具把测试默认钉到 `dev` 模式
（演示态裸头）。**验证 proxy 模式（签名身份）的测试在用例内 monkeypatch 覆盖回 `proxy`**。
生产默认仍是 proxy（仅测试默认 dev）。
"""

from __future__ import annotations

import pytest

from backend.app.api import app as app_module


@pytest.fixture(autouse=True)
def _test_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """审计库钉 :memory:（杜绝 audit.db 落工作树）+ 认证默认 dev 模式（proxy 测试自行覆盖）。

    L-H2/L-M4 commit 2 起：audit/policy 端点 require_role 后，dev 模式还需 X-User-Role
    头才能获得对应角色；本夹具默认注入 admin（含 auditor 等所有角色），让老测试
    （只关心 200/内容）继续 PASS。要测 403 守门的新测试需在 monkeypatch 把默认头改空。
    """
    monkeypatch.setattr(app_module, "_AUDIT_DB_PATH", ":memory:")
    monkeypatch.setenv("KYLIN_AUTH_MODE", "dev")
    monkeypatch.setenv("KYLIN_TEST_X_USER_ROLE", "admin,auditor,operator")


# ============================================================
# L-B2 偏差 4: proxy 模式严测 fixture
# ============================================================


@pytest.fixture
def proxy_mode_client(monkeypatch):
    """proxy 模式 TestClient wrapper: monkeypatch KYLIN_AUTH_MODE=proxy.

    Usage:
        def test_x(client):
            headers = proxy_signed_headers("alice", roles="auditor")
            resp = client.get("/api/audit/traces", headers=headers)
            assert resp.status_code == 200
    """
    import asyncio

    import httpx

    from backend.app.api.app import create_app, lifespan

    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    def _get(path: str, headers: dict | None = None):
        async def _run():
            async with lifespan(app):
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                    return await c.get(path, headers=headers or {})

        return asyncio.run(_run())

    return _get


@pytest.fixture
def proxy_signed_headers(monkeypatch):
    """生成 4 HMAC-signed headers (X-Auth-User / X-Auth-Roles / X-Auth-Timestamp / X-Auth-Signature).

    proxy 模式 verify_proxy_identity 会通过校验,principal.user == user.
    """
    import hashlib
    import hmac
    import os
    import time

    def _make(user: str, roles: str | None = None, secret: str | None = None) -> dict:
        # 必须 setenv 让 verify_proxy_identity request-time 拿得到
        os.environ.setdefault("KYLIN_PROXY_AUTH_SECRET", "kylin-test-signing-secret")
        signing_secret = secret if secret is not None else os.environ["KYLIN_PROXY_AUTH_SECRET"]
        timestamp = str(int(time.time()))
        roles_str = roles or ""
        # 与 backend.app.api.auth._canonical() 同口径：user \n roles \n timestamp
        canonical = f"{user}\n{roles_str}\n{timestamp}".encode()
        sig = hmac.new(signing_secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
        return {
            "X-Auth-User": user,
            "X-Auth-Roles": roles_str,
            "X-Auth-Timestamp": timestamp,
            "X-Auth-Signature": sig,
        }

    return _make


@pytest.fixture
def proxy_client_factory(monkeypatch):
    """同 proxy_mode_client + 可替换 secret."""
    return proxy_mode_client.__wrapped__  # type: ignore[attr-defined]
