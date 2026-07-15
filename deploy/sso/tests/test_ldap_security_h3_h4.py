"""H3+H4 安全修复守门测试（deploy/sso/ldap_client.py）。

H3 — 空口令 LDAP bind 绕过防护：
  空/None 口令在 authenticate 入口 + _bind_user 入口一律拒，
  不给 ldap3 unauthenticated bind（RFC 4513）绕过的机会。

H4 — LDAP 明文无 TLS 防护：
  ldaps:// scheme 或 KYLIN_LDAP_USE_TLS=true 时启用 use_ssl + Tls(CERT_REQUIRED)，
  service 账号 bind 口令不明文过网。
"""

from __future__ import annotations

import ssl
from typing import Any

import pytest

from deploy.sso.ldap_client import (
    LdapClient,
    _build_server,
    _tls_enabled,
)

# 真模式必填 env（与 ldap_client._REQUIRED_REAL_ENV 对齐），供 H3 真模式用例钉入。
_REAL_ENV = {
    "KYLIN_LDAP_URL": "ldap://ldap.kylin.test",
    "KYLIN_LDAP_BIND_DN": "cn=svc,dc=kylin,dc=test",
    "KYLIN_LDAP_BIND_PASSWORD": "svc-secret",
    "KYLIN_LDAP_BASE_DN": "dc=kylin,dc=test",
    "KYLIN_LDAP_USER_FILTER": "(uid={})",
    "KYLIN_LDAP_GROUP_ATTR": "memberOf",
}


def _set_real_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    """钉真模式 env（KYLIN_LDAP_MOCK=false + 必填项），可覆盖单项。"""
    monkeypatch.setenv("KYLIN_LDAP_MOCK", "false")
    for k, v in {**_REAL_ENV, **overrides}.items():
        monkeypatch.setenv(k, v)


# ============================================================
# H3 — 空口令绕过防护
# ============================================================


class TestH3EmptyPassword:
    def test_mock_mode_empty_password_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """mock 模式：正确用户名 + 空口令 → 拒（不因 entry 存在而放行）。"""
        monkeypatch.setenv("KYLIN_LDAP_MOCK", "true")
        client = LdapClient()
        assert client.authenticate("admin", "") is False

    def test_mock_mode_correct_password_still_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """回归护栏：mock 模式正确口令仍应通过（防护没误伤正常路径）。"""
        monkeypatch.setenv("KYLIN_LDAP_MOCK", "true")
        client = LdapClient()
        assert client.authenticate("admin", "kylin123") is True

    def test_real_mode_empty_password_rejected_before_ldap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """真模式：空口令必须在触达 ldap3 之前被拒（否则 unauthenticated bind 绕过）。

        注入一个会记录"是否被调用"的 fake ldap3，断言空口令路径下它从未被触碰。
        """
        _set_real_env(monkeypatch)
        client = LdapClient()

        called = {"connection": False}

        class _FakeLdap3:
            SUBTREE = "SUBTREE"
            NONE = "NONE"

            @staticmethod
            def Server(*_a: Any, **_k: Any) -> Any:  # noqa: N802
                return object()

            @staticmethod
            def Connection(*_a: Any, **_k: Any) -> Any:  # noqa: N802
                called["connection"] = True
                raise AssertionError("空口令不应触达 ldap3.Connection")

        monkeypatch.setattr("deploy.sso.ldap_client._import_ldap3", lambda: _FakeLdap3)
        assert client.authenticate("admin", "") is False
        assert called["connection"] is False

    def test_real_mode_none_password_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """真模式 _bind_user 直接传 None 口令 → 拒（入口防护）。"""
        _set_real_env(monkeypatch)
        client = LdapClient()

        class _FakeLdap3:
            @staticmethod
            def Connection(*_a: Any, **_k: Any) -> Any:  # noqa: N802
                raise AssertionError("None 口令不应触达 ldap3.Connection")

        assert client._bind_user(_FakeLdap3, "admin", "") is False  # type: ignore[arg-type]


# ============================================================
# H4 — TLS 配置生效
# ============================================================


class _FakeTls:
    """记录 Tls 构造参数供断言。"""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _FakeServer:
    """记录 Server 构造参数供断言。"""

    def __init__(self, url: str, **kwargs: Any) -> None:
        self.url = url
        self.kwargs = kwargs


class _FakeLdap3TLS:
    NONE = "NONE"
    Tls = _FakeTls
    Server = _FakeServer


class TestH4Tls:
    def test_tls_enabled_by_ldaps_scheme(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ldaps:// scheme → TLS 开（不依赖 env 开关）。"""
        monkeypatch.delenv("KYLIN_LDAP_USE_TLS", raising=False)
        assert _tls_enabled("ldaps://ldap.kylin.test") is True

    def test_tls_enabled_by_env_switch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KYLIN_LDAP_USE_TLS=true + ldap:// → TLS 开。"""
        monkeypatch.setenv("KYLIN_LDAP_USE_TLS", "true")
        assert _tls_enabled("ldap://ldap.kylin.test") is True

    def test_tls_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """普通 ldap:// + 无 env 开关 → TLS 关（保持向后兼容默认）。"""
        monkeypatch.delenv("KYLIN_LDAP_USE_TLS", raising=False)
        assert _tls_enabled("ldap://ldap.kylin.test") is False

    def test_build_server_tls_on_sets_use_ssl_and_cert_required(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TLS 开时：Server 传 use_ssl=True + Tls(validate=CERT_REQUIRED)。"""
        monkeypatch.setenv("KYLIN_LDAP_USE_TLS", "true")
        server = _build_server(_FakeLdap3TLS, "ldap://ldap.kylin.test")
        assert isinstance(server, _FakeServer)
        assert server.kwargs.get("use_ssl") is True
        tls = server.kwargs.get("tls")
        assert isinstance(tls, _FakeTls)
        assert tls.kwargs.get("validate") == ssl.CERT_REQUIRED

    def test_build_server_tls_off_no_ssl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TLS 关时：Server 不传 use_ssl（明文，保持原行为）。"""
        monkeypatch.delenv("KYLIN_LDAP_USE_TLS", raising=False)
        server = _build_server(_FakeLdap3TLS, "ldap://ldap.kylin.test")
        assert isinstance(server, _FakeServer)
        assert "use_ssl" not in server.kwargs

    def test_build_server_ldaps_uses_ca_cert_when_provided(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """指定 KYLIN_LDAP_CA_CERT 时透传给 Tls(ca_certs_file)。"""
        monkeypatch.setenv("KYLIN_LDAP_CA_CERT", "/etc/ssl/kylin-ca.pem")
        server = _build_server(_FakeLdap3TLS, "ldaps://ldap.kylin.test")
        tls = server.kwargs.get("tls")
        assert isinstance(tls, _FakeTls)
        assert tls.kwargs.get("ca_certs_file") == "/etc/ssl/kylin-ca.pem"
