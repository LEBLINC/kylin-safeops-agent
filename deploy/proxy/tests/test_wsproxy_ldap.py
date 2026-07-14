"""A2.1: wsproxy.py 真接 LDAP 守门测试（2 用例 T6-T7）.

T6 mock ldap_client.authenticate 返 True → 注入 X-Auth-* 4 头
T7 mock 返 False → 鉴权失败返回 None（caller 据此 401）
"""

from __future__ import annotations

from unittest import mock

import pytest

from deploy.proxy.wsproxy import authenticate_and_build_headers
from deploy.sso.ldap_client import LdapClient, LdapUser


def _b64_basic(username: str, password: str) -> str:
    import base64

    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


def test_t6_wsproxy_real_ldap_authenticate_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """T6: ldap_client.authenticate 返 True + get_user 返合法用户 → 注入 X-Auth-* 4 头."""
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", "test-secret-wsproxy-t6")
    client = mock.MagicMock(spec=LdapClient)
    client.authenticate.return_value = True
    client.get_user.return_value = LdapUser(
        username="alice",
        display_name="Alice",
        groups=["kylin-ops"],
        roles=["operator"],
    )
    headers = authenticate_and_build_headers(
        client,
        _b64_basic("alice", "pw"),
        method="GET",
        path="/api/chat/t1/events",
    )
    assert headers is not None, "T6: 鉴权通过应返回签名头字典"
    assert headers["X-Auth-User"] == "alice"
    assert headers["X-Auth-Roles"] == "operator"
    assert "X-Auth-Signature" in headers
    assert "X-Auth-Method" in headers
    assert "X-Auth-Path" in headers
    assert "X-Auth-Body-Sha" in headers
    assert "X-Auth-Nonce" in headers
    client.authenticate.assert_called_once_with("alice", "pw")


def test_t7_wsproxy_real_ldap_authenticate_fail() -> None:
    """T7: ldap_client.authenticate 返 False → 鉴权失败返回 None（caller 401）."""
    client = mock.MagicMock(spec=LdapClient)
    client.authenticate.return_value = False
    headers = authenticate_and_build_headers(
        client,
        _b64_basic("alice", "wrong-pw"),
        method="GET",
        path="/api/chat/t1/events",
    )
    assert headers is None, "T7: 鉴权失败应返回 None (caller 401)"
    client.get_user.assert_not_called()
