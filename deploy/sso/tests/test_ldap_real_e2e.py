"""A1.3: 真接 LDAP 反代签名链路 roundtrip 守门测试.

T6: mock LdapClient + 真 HMAC 签名 → 验签通过 → Principal 解析完整 DN.
"""

from __future__ import annotations

import time

import pytest


def test_t6_ldap_real_signing_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """T6: 真接 HMAC 签名 → backend verify 通过 → Principal 完整."""
    secret = "test-secret-t6-a1.3"
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", secret)

    # proxy.py 的 SECRET 在 import time 读 env — 重新 import 让 SECRET 反映 monkeypatch
    import importlib

    import deploy.proxy.proxy as proxy_mod

    importlib.reload(proxy_mod)
    from backend.app.api.auth import verify_proxy_identity

    sign = proxy_mod.sign

    user = "ldap_alice"
    roles = "admin,operator"
    ts = str(int(time.time()))
    sig = sign(user, roles, ts, "GET", "/api/audit/traces", "abc", "unique-n6")
    p = verify_proxy_identity(
        user=user,
        roles=roles,
        timestamp=ts,
        signature=sig,
        method="GET",
        path="/api/audit/traces",
        body_sha="abc",
        nonce="unique-n6",
        now=float(ts) + 5.0,
    )
    assert p is not None, f"T6: 真接 LDAP 链路应 verify pass, got {p!r}"
    assert p.user == user
    assert p.roles == frozenset({"admin", "operator"})
