"""A1.1: HMAC canonical v2 (method/path/body/nonce 绑定) 守门测试。

覆盖 3 用例:
  T1 恶意改 method → 签名失配 401
  T2 恶意改 body → 签名失配 401
  T3 v2 canonical 输出 7 字段含 4 新字段 (method/path/body/nonce)
"""

from __future__ import annotations

import pytest

from backend.app.api.auth import _canonical, sign_identity, verify_proxy_identity

# ---- T1: HMAC binds method/path ----


def test_t1_hmac_binds_method(monkeypatch: pytest.MonkeyPatch) -> None:
    """T1: 改 method 后, verify_proxy_identity 返 None (签名失配)."""
    secret = "test-secret-t1"
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", secret)
    user = "alice"
    roles = "admin"
    ts = "1700000000"
    sig = sign_identity(
        user, roles, ts, secret, method="GET", path="/api/x", body_sha="abc", nonce="n1"
    )
    p = verify_proxy_identity(
        user=user,
        roles=roles,
        timestamp=ts,
        signature=sig,
        method="GET",
        path="/api/x",
        body_sha="abc",
        nonce="n1",
        now=1700000000.0,
    )
    assert p is not None, "T1: 正确 method 应 pass"
    # 改 method → fail
    p2 = verify_proxy_identity(
        user=user,
        roles=roles,
        timestamp=ts,
        signature=sig,
        method="POST",
        path="/api/x",
        body_sha="abc",
        nonce="n1",
        now=1700000000.0,
    )
    assert p2 is None, f"T1: 改 method 应 401, got {p2!r}"


# ---- T2: HMAC binds body_sha ----


def test_t2_hmac_binds_body_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    """T2: 改 body_sha 后, verify_proxy_identity 返 None."""
    secret = "test-secret-t2"
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", secret)
    user = "alice"
    roles = "admin"
    ts = "1700000000"
    sig = sign_identity(
        user, roles, ts, secret, method="POST", path="/api/x", body_sha="abc", nonce="n2"
    )
    p = verify_proxy_identity(
        user=user,
        roles=roles,
        timestamp=ts,
        signature=sig,
        method="POST",
        path="/api/x",
        body_sha="DIFFERENT",
        nonce="n2",
        now=1700000000.0,
    )
    assert p is None, f"T2: 改 body 应 401, got {p!r}"


# ---- T3: HMAC canonical v2 输出 7 字段 ----


def test_t3_canonical_v2_7_fields() -> None:
    """T3: _canonical 传入 method/path/body/nonce → 输出 7 字段含 4 新字段."""
    out = _canonical("u", "r", "1", method="GET", path="/p", body_sha="abc", nonce="n")
    assert "\n" in out
    parts = out.split("\n")
    assert len(parts) == 7, f"T3: v2 应 7 字段, got {len(parts)}"
    assert parts[3] == "GET"
    assert parts[4] == "/p"
    assert parts[5] == "abc"
    assert parts[6] == "n"
