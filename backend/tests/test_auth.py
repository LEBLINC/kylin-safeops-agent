"""接线增量·任务甲 — 反代签名身份验证单元测试（verify_proxy_identity / sign_identity）。

纯函数单测，不起 app。密钥经 monkeypatch env 注入测试值；fail-closed 全覆盖。
"""

from __future__ import annotations

import time

import pytest

from backend.app.api.auth import Principal, sign_identity, verify_proxy_identity

_SECRET = "unit-test-secret"


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)


def _headers(user: str, roles: str, *, ts: int | None = None, secret: str = _SECRET) -> dict:
    timestamp = str(ts if ts is not None else int(time.time()))
    return {
        "user": user,
        "roles": roles,
        "timestamp": timestamp,
        "signature": sign_identity(user, roles, timestamp, secret),
    }


def test_valid_signature_returns_principal() -> None:
    p = verify_proxy_identity(**_headers("alice", "operator,admin"))
    assert isinstance(p, Principal)
    assert p.user == "alice"
    assert p.roles == frozenset({"operator", "admin"})


def test_roles_normalized_lowercase() -> None:
    p = verify_proxy_identity(**_headers("bob", "Admin, Operator"))
    assert p is not None
    assert p.roles == frozenset({"admin", "operator"})


def test_tampered_roles_returns_none() -> None:
    """签名按 operator 计算，但 roles 头改成 admin → HMAC 不匹配 → None（伪造无效）。"""
    h = _headers("mallory", "operator")
    h["roles"] = "admin"  # 篡改声称角色，不重签
    assert verify_proxy_identity(**h) is None


def test_tampered_user_returns_none() -> None:
    h = _headers("alice", "admin")
    h["user"] = "eve"
    assert verify_proxy_identity(**h) is None


def test_tampered_timestamp_returns_none() -> None:
    h = _headers("alice", "admin")
    h["timestamp"] = str(int(h["timestamp"]) + 1)  # 改时间戳使签名失配
    assert verify_proxy_identity(**h) is None


def test_expired_timestamp_returns_none() -> None:
    assert verify_proxy_identity(**_headers("alice", "admin", ts=int(time.time()) - 400)) is None


def test_future_timestamp_returns_none() -> None:
    assert verify_proxy_identity(**_headers("alice", "admin", ts=int(time.time()) + 400)) is None


def test_wrong_signature_returns_none() -> None:
    h = _headers("alice", "admin")
    h["signature"] = "deadbeef" * 8
    assert verify_proxy_identity(**h) is None


def test_secret_not_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KYLIN_PROXY_AUTH_SECRET", raising=False)
    assert verify_proxy_identity(**_headers("alice", "admin", secret="whatever")) is None


def test_missing_fields_return_none() -> None:
    base = _headers("alice", "admin")
    for missing in ("user", "roles", "timestamp", "signature"):
        h = dict(base)
        h[missing] = None
        assert verify_proxy_identity(**h) is None, f"{missing} 缺失应 fail-closed"


def test_non_numeric_timestamp_returns_none() -> None:
    h = _headers("alice", "admin")
    h["timestamp"] = "not-a-number"
    assert verify_proxy_identity(**h) is None


def test_now_override_for_determinism() -> None:
    """显式传 now 可确定性校验时间窗。"""
    ts = 1_000_000
    h = {
        "user": "alice",
        "roles": "admin",
        "timestamp": str(ts),
        "signature": sign_identity("alice", "admin", str(ts), _SECRET),
    }
    assert verify_proxy_identity(**h, now=ts + 10) is not None
    assert verify_proxy_identity(**h, now=ts + 1000) is None
