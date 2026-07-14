"""A1.2: nonce LRU 缓存 + 时效窗口 守门测试.

覆盖 2 用例:
  T4 同 nonce 第二次 verify → None (防重放)
  T5 timestamp 超出 300s 窗口 → None
"""

from __future__ import annotations

import pytest

from backend.app.api.auth import sign_identity, verify_proxy_identity


def test_t4_nonce_replay_in_window_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """T4: 同 nonce 二次 verify (在 300s 窗口内) → 第二次 None."""
    secret = "test-secret-t4"
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", secret)
    monkeypatch.setattr(
        "backend.app.api.auth._SEEN_NONCES", {}, raising=True
    )
    user = "alice"
    roles = "admin"
    ts = "1700000000"
    sig = sign_identity(
        user, roles, ts, secret,
        method="GET", path="/p", body_sha="abc", nonce="unique-n1",
    )
    p1 = verify_proxy_identity(
        user=user, roles=roles, timestamp=ts, signature=sig,
        method="GET", path="/p", body_sha="abc", nonce="unique-n1",
        now=1700000100.0,  # +100s
    )
    assert p1 is not None, f"T4: 第一次 verify 应 pass, got {p1!r}"
    p2 = verify_proxy_identity(
        user=user, roles=roles, timestamp=ts, signature=sig,
        method="GET", path="/p", body_sha="abc", nonce="unique-n1",
        now=1700000100.0,
    )
    assert p2 is None, f"T4: 同 nonce 第二次 verify 应 None (防重放), got {p2!r}"


def test_t5_nonce_expired_outside_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """T5: timestamp 距 now > 300s → None (防时窗重放)."""
    secret = "test-secret-t5"
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", secret)
    user = "alice"
    roles = "admin"
    ts = "1700000000"
    sig = sign_identity(
        user, roles, ts, secret,
        method="GET", path="/p", body_sha="abc", nonce="n5",
    )
    # now 距 ts 301s → 超出 300s 窗口
    p = verify_proxy_identity(
        user=user, roles=roles, timestamp=ts, signature=sig,
        method="GET", path="/p", body_sha="abc", nonce="n5",
        now=1700000301.0,
    )
    assert p is None, f"T5: ts 距 now 301s 应 None, got {p!r}"
