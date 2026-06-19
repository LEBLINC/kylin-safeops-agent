import os

import pytest


@pytest.fixture
def real_env(monkeypatch):
    """装配真模式 env：mock=false + 全套必填 env。"""
    monkeypatch.setenv("KYLIN_LDAP_MOCK", "false")
    monkeypatch.setenv("KYLIN_LDAP_URL", "ldap://ldap.test:389")
    monkeypatch.setenv("KYLIN_LDAP_BIND_DN", "cn=admin,dc=test,dc=com")
    monkeypatch.setenv("KYLIN_LDAP_BIND_PASSWORD", "secret")
    monkeypatch.setenv("KYLIN_LDAP_BASE_DN", "dc=test,dc=com")
    monkeypatch.setenv("KYLIN_LDAP_USER_FILTER", "(uid={})")
    monkeypatch.setenv("KYLIN_LDAP_GROUP_ATTR", "memberOf")
    return monkeypatch


class TestLdapClientMock:
    def setup_method(self):
        os.environ["KYLIN_LDAP_MOCK"] = "true"
        from deploy.sso.ldap_client import LdapClient

        self.client = LdapClient()

    def test_authenticate_valid_user_correct_password(self):
        assert self.client.authenticate("admin", "kylin123") is True

    def test_authenticate_valid_user_wrong_password(self):
        assert self.client.authenticate("admin", "wrong") is False

    def test_authenticate_nonexistent_user(self):
        assert self.client.authenticate("nonexistent", "kylin123") is False

    def test_get_user_admin_has_admin_role(self):
        user = self.client.get_user("admin")
        assert user is not None
        assert "admin" in user.roles
        assert "operator" in user.roles

    def test_get_user_viewer_has_viewer_role(self):
        user = self.client.get_user("viewer")
        assert user is not None
        assert "viewer" in user.roles

    def test_get_user_nonexistent_returns_none(self):
        assert self.client.get_user("nonexistent") is None

    def test_mock_mode_no_network(self, monkeypatch):
        """mock mode should not trigger network connections"""
        assert self.client.mock is True
        assert self.client.authenticate("admin", "kylin123") is True


class TestLdapClientReal:
    """P1b 真模式 6 用例——ldap3 全 mock，不触网。

    关键安全断言：
    - 不区分"用户不存在" vs "密码错"（防枚举）
    - LDAP injection 转义（* ( ) \\ NUL → \\2a \\28 \\29 \\5c \\00）
    - size_limit=1 + 超时 5s
    - 异常吞掉不抛
    """

    @staticmethod
    def _make_client(monkeypatch):
        """monkeypatch KYLIN_LDAP_MOCK=false + 注入全部必需 env。"""
        env = {
            "KYLIN_LDAP_MOCK": "false",
            "KYLIN_LDAP_URL": "ldap://ldap.test:389",
            "KYLIN_LDAP_BIND_DN": "cn=svc,dc=test,dc=com",
            "KYLIN_LDAP_BIND_PASSWORD": "secret",
            "KYLIN_LDAP_BASE_DN": "dc=test,dc=com",
            "KYLIN_LDAP_USER_FILTER": "(uid={})",
            "KYLIN_LDAP_GROUP_ATTR": "memberOf",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        from deploy.sso.ldap_client import LdapClient

        return LdapClient()

    @staticmethod
    def _patch_ldap3(monkeypatch, bind_result=None, bind_user_raises=None, search_entries=None):
        """注入 fake ldap3 模块——返回 fake module via sys.modules patch。

        bind_result: True=bind 成功 / False=bind 失败 / None=抛 LDAPException
        search_entries: search 返的 entries 列表（每个 entry 是 dict-like 含 attrs）
        """
        import sys
        from unittest import mock as _mock

        fake_ldap3 = _mock.MagicMock()
        # Server(...) 类
        fake_server_inst = _mock.MagicMock()
        fake_ldap3.Server.return_value = fake_server_inst

        # Connection(Server) 实例：auto_bind=True 走 __init__ → 我们用 side_effect 控 bind
        fake_conn = _mock.MagicMock()
        # 默认 search 结果（空）；bind_result=True 时默认返一个 entry（让 auth 路径走通）
        success = _mock.MagicMock()
        success.__bool__ = lambda self: True
        fake_conn.search.return_value = success

        # search 行为：search_entries 已显式传 → 用之；否则 fake_conn.entries
        # 由 test 自行管理（test 可直接 `fake_conn.entries = [entry]` 自定义 attrs）。
        if search_entries is not None:
            fake_conn.entries = search_entries

        def fake_search(*args, **kwargs):
            return success

        fake_conn.search.side_effect = fake_search
        fake_conn.entries = fake_search() and fake_conn.entries or []

        # bind 失败 / 异常 / 成功 — 通过 Connection 构造的 side_effect 模拟
        # auto_bind=True 行为：ldap3 在 __init__ 内 bind，失败就 raise。
        def fake_connection_ctor(*args, **kwargs):
            if bind_user_raises is not None:
                raise bind_user_raises
            if bind_result is False:
                # 不从 ldap3 拿真异常类（避免 __init__ 触发真实 ldap3 加载）
                raise fake_ldap3.core.exceptions.LDAPBindError("invalidCredentials")
            return fake_conn  # bind_result=True / None 都返 fake_conn

        fake_ldap3.Connection.side_effect = fake_connection_ctor
        # fake_bind 仍保留作兼容（prod 显式调 conn.bind() 走 service Connection）

        # Strategy 不重要，MagicMock 兜底
        fake_ldap3.SAFE_SYNC = object()

        # 子模块异常类型
        fake_ldap3.core.exceptions.LDAPBindError = type("LDAPBindError", (Exception,), {})
        fake_ldap3.core.exceptions.LDAPException = type("LDAPException", (Exception,), {})

        monkeypatch.setitem(sys.modules, "ldap3", fake_ldap3)
        monkeypatch.setitem(sys.modules, "ldap3.core", fake_ldap3.core)
        monkeypatch.setitem(sys.modules, "ldap3.core.exceptions", fake_ldap3.core.exceptions)
        return fake_conn, fake_server_inst, fake_ldap3

    def test_real_authenticate_success(self, monkeypatch):
        """真模式：bind 成功 → authenticate=True。"""
        from deploy.sso.ldap_client import LdapClient

        env = {
            "KYLIN_LDAP_MOCK": "false",
            "KYLIN_LDAP_URL": "ldap://ldap.test:389",
            "KYLIN_LDAP_BIND_DN": "cn=svc,dc=test,dc=com",
            "KYLIN_LDAP_BIND_PASSWORD": "secret",
            "KYLIN_LDAP_BASE_DN": "dc=test,dc=com",
            "KYLIN_LDAP_USER_FILTER": "(uid={})",
            "KYLIN_LDAP_GROUP_ATTR": "memberOf",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        self._patch_ldap3(monkeypatch, bind_result=True)

        client = LdapClient()
        assert client.authenticate("alice", "pw") is True

    def test_real_authenticate_wrong_password_and_unknown_user_both_false(self, monkeypatch):
        """真模式：bind 失败（密码错 OR 用户不存在）→ 一律 False（防枚举）。"""
        from deploy.sso.ldap_client import LdapClient

        env = {
            "KYLIN_LDAP_MOCK": "false",
            "KYLIN_LDAP_URL": "ldap://ldap.test:389",
            "KYLIN_LDAP_BIND_DN": "cn=svc,dc=test,dc=com",
            "KYLIN_LDAP_BIND_PASSWORD": "secret",
            "KYLIN_LDAP_BASE_DN": "dc=test,dc=com",
            "KYLIN_LDAP_USER_FILTER": "(uid={})",
            "KYLIN_LDAP_GROUP_ATTR": "memberOf",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        self._patch_ldap3(monkeypatch, bind_result=False)

        client = LdapClient()
        # 密码错
        assert client.authenticate("alice", "wrong") is False
        # 用户不存在（ldap3 bind 都返 LDAPBindError("invalidCredentials")）
        assert client.authenticate("ghost", "any") is False

    def test_real_authenticate_ldap_exception_swallowed(self, monkeypatch):
        """真模式：连接异常 → 吞掉返 False（不暴露 LDAP 状态）。"""
        from deploy.sso.ldap_client import LdapClient

        # 用本地 mock 异常类（不 import ldap3.core.exceptions，否则触发真 ldap3 加载）
        class _FakeLdapException(Exception):
            pass

        env = {
            "KYLIN_LDAP_MOCK": "false",
            "KYLIN_LDAP_URL": "ldap://ldap.test:389",
            "KYLIN_LDAP_BIND_DN": "cn=svc,dc=test,dc=com",
            "KYLIN_LDAP_BIND_PASSWORD": "secret",
            "KYLIN_LDAP_BASE_DN": "dc=test,dc=com",
            "KYLIN_LDAP_USER_FILTER": "(uid={})",
            "KYLIN_LDAP_GROUP_ATTR": "memberOf",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        self._patch_ldap3(monkeypatch, bind_user_raises=_FakeLdapException("network down"))

        client = LdapClient()
        assert client.authenticate("alice", "pw") is False  # 异常吞掉，不抛

    def test_real_injection_escape_in_bind_dn(self, monkeypatch):
        """真模式：username 含 * → escape（防 LDAP injection 在 bind DN）。"""
        from deploy.sso.ldap_client import _escape_ldap_filter

        assert _escape_ldap_filter("alice*") == "alice\\2a"
        assert _escape_ldap_filter("a(b)c") == "a\\28b\\29c"
        assert _escape_ldap_filter("a\\b") == "a\\5cb"
        assert _escape_ldap_filter("a\x00b") == "a\\00b"

    def test_real_size_limit_one_and_timeouts(self, monkeypatch):
        """真模式：search size_limit=1 + connect_timeout=5 + receive_timeout=5。"""

        from deploy.sso.ldap_client import LdapClient

        env = {
            "KYLIN_LDAP_MOCK": "false",
            "KYLIN_LDAP_URL": "ldap://ldap.test:389",
            "KYLIN_LDAP_BIND_DN": "cn=svc,dc=test,dc=com",
            "KYLIN_LDAP_BIND_PASSWORD": "secret",
            "KYLIN_LDAP_BASE_DN": "dc=test,dc=com",
            "KYLIN_LDAP_USER_FILTER": "(uid={})",
            "KYLIN_LDAP_GROUP_ATTR": "memberOf",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        fake_conn, fake_server, fake_ldap3 = self._patch_ldap3(monkeypatch, bind_result=True)

        # 构造 search 返回一个 entry（prod 用 entry["memberOf"] 访问，故用 __getitem__）
        # fake entry 须支持 __getitem__ 与 __contains__；MagicMock 默认 __contains__ 返 False。
        class _V:
            def __init__(self, value):
                self.value = value

            # 兼容 prod 用 .value（单值）或 .values（列表）访问
            @property
            def values(self):
                if isinstance(self.value, list):
                    return self.value
                return [self.value]

        class _FakeEntry:
            def __init__(self, attrs):
                self._attrs = attrs

            def __getitem__(self, k):
                return self._attrs[k]

            def __contains__(self, k):
                return k in self._attrs

            def __getattr__(self, k):  # 支持 entry.cn / entry.memberOf 属性访问
                if k in self._attrs:
                    return self._attrs[k]
                raise AttributeError(k)

        fake_entry = _FakeEntry(
            {
                "cn": _V("Alice"),
                "memberOf": _V(["kylin-admins"]),  # 默认 _group_role_map 的 key
            }
        )
        fake_conn.entries = [fake_entry]
        fake_conn.search.return_value = True

        client = LdapClient()
        user = client.get_user("alice")
        assert user is not None
        assert user.username == "alice"
        # role 映射：kylin-admins → admin
        assert "admin" in user.roles

        # size_limit=1
        search_kwargs = fake_conn.search.call_args.kwargs
        assert search_kwargs.get("size_limit") == 1
        # Server connect_timeout=5
        server_kwargs = fake_ldap3.Server.call_args.kwargs  # type: ignore[attr-defined]
        assert server_kwargs.get("connect_timeout") == 5
        # Connection receive_timeout=5
        conn_kwargs = fake_ldap3.Connection.call_args.kwargs  # type: ignore[attr-defined]
        assert conn_kwargs.get("receive_timeout") == 5

    def test_real_get_user_with_escaped_username(self, monkeypatch):
        """真模式：get_user 传入特殊字符 username → search filter 转义。"""

        env = {
            "KYLIN_LDAP_MOCK": "false",
            "KYLIN_LDAP_URL": "ldap://ldap.test:389",
            "KYLIN_LDAP_BIND_DN": "cn=svc,dc=test,dc=com",
            "KYLIN_LDAP_BIND_PASSWORD": "secret",
            "KYLIN_LDAP_BASE_DN": "dc=test,dc=com",
            "KYLIN_LDAP_USER_FILTER": "(uid={})",
            "KYLIN_LDAP_GROUP_ATTR": "memberOf",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        fake_conn, _, _ = self._patch_ldap3(monkeypatch, bind_result=True)

        # 重写 search 让其直接返空 entries（覆盖默认的 bind_result=True 自动 entry）
        def empty_search(*args, **kwargs):
            fake_conn.entries = []
            return True

        fake_conn.search.side_effect = empty_search

        from deploy.sso.ldap_client import LdapClient

        client = LdapClient()
        # username 含 * → filter 应该 escape
        result = client.get_user("ali*ce")
        assert result is None  # 没找到 → None

        search_kwargs = fake_conn.search.call_args
        assert search_kwargs is not None, "应调过 search"
        # filter 应含 \\2a（escape 后的 *）
        assert "\\2a" in search_kwargs.kwargs.get("search_filter", "")
