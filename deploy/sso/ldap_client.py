"""LdapClient（反代 SSO 真 LDAP 客户端，P1b 真实现）。

P1a：mock 模式 + 接口契约（authenticate 返回 bool + get_user 返回 LdapUser）。
P1b：**ldap3 真实现**替换 NotImplementedError——mock 模式保留（demo/单测/CI）。

**架构**：
- mock（`KYLIN_LDAP_MOCK=true`）：单文件 mock，**行为与 P1a 一致**——7 mock 单元测零回归。
- 真（`KYLIN_LDAP_MOCK=false`）：ldap3.Connection + 简单 bind + search(SUBTREE,
  size_limit=1) 拿 user DN 与组信息。**纯 Python**，不依赖系统 libldap（与 ADR-0001
  精神一致，LoongArch 移植风险低）。

**安全红线**（P1b 设计要求）：
1. **不区分"用户不存在" vs "密码错"** —— 防用户枚举。bind 失败 + search 0 条统一返 None/False。
2. **LDAP injection 防御**——`* ( ) \\ NUL` 在搜索过滤前 escape。
3. **`size_limit=1`**——防滥用。
4. **超时收紧**——`connect_timeout=5, receive_timeout=5`，防 DoS。
5. **异常吞掉不抛**——不暴露 LDAP server 状态给攻击者。
6. **不引 python-ldap**——纯 Python 优先；`ldap3<3.0` 锁版本防传递依赖漂移。

**依赖注入**：
- ldap3 是**真模式的运行时依赖**，不是测试依赖。
- 真模式下 ldap3 import 失败 → `authenticate/get_user` 返 None/False（不抛，避免代理宕）。
  启动期 `LdapClient.__init__` 也不 throw——给 proxy_basic_auth.py 失败软降级机会。
"""

from __future__ import annotations  # Python 3.9 compat: str | None / X | Y union syntax

import json
import os
import ssl
from dataclasses import dataclass
from typing import Any

_DEFAULT_GROUP_ROLE_MAP: dict[str, str] = {
    "kylin-admins": "admin",
    "kylin-ops": "operator",
    "kylin-auditors": "auditor",
    "kylin-viewers": "viewer",
}

_MOCK_USERS: dict[str, tuple] = {
    "admin": ("kylin123", "Admin User", ["kylin-admins", "kylin-ops"]),
    "operator": ("kylin123", "Operator User", ["kylin-ops"]),
    "auditor": ("kylin123", "Auditor User", ["kylin-auditors"]),
    "viewer": ("kylin123", "Viewer User", ["kylin-viewers"]),
}

# 真模式必填 env 列表（P1b #4 必填 env 检查）
_REQUIRED_REAL_ENV = (
    "KYLIN_LDAP_URL",
    "KYLIN_LDAP_BIND_DN",
    "KYLIN_LDAP_BIND_PASSWORD",
    "KYLIN_LDAP_BASE_DN",
    "KYLIN_LDAP_USER_FILTER",
    "KYLIN_LDAP_GROUP_ATTR",
)

# LDAP injection escape 字符表（P1b #2 安全红线）
_LDAP_ESCAPE_CHARS = {
    "\\": r"\5c",
    "*": r"\2a",
    "(": r"\28",
    ")": r"\29",
    "\x00": r"\00",
}


def _normalize_group_name(dn: str) -> str:
    """LDAP DN → 裸名（运维友好：裸名配置对真 LDAP 也成立）。
    cn=kylin-admins,ou=groups,dc=kylin,dc=test → kylin-admins
    已是裸名 / 无 cn= 前缀时原样返回（兼容全-DN 键配置）。
    """
    low = dn.lower()
    if low.startswith("cn="):
        return dn.split(",")[0][3:]
    return dn


def _parse_group_role_map(raw: str | None) -> dict[str, str]:
    if raw is None:
        return dict(_DEFAULT_GROUP_ROLE_MAP)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return dict(_DEFAULT_GROUP_ROLE_MAP)


def _escape_ldap_filter(value: str) -> str:
    """Escape LDAP filter special chars（RFC 4515）：\\ * ( ) NUL。

    在把 username 拼进 user_filter 模板前必须 escape，否则攻击者可通过
    `*` 触发 wildcard 搜索拿到所有用户 hash（防 enumeration）。
    """
    out: list[str] = []
    for ch in value:
        out.append(_LDAP_ESCAPE_CHARS.get(ch, ch))
    return "".join(out)


def _import_ldap3() -> Any | None:
    """延迟 import ldap3——mock 模式不装包也能跑（CI 友好）。

    真模式失败返 None（不抛），让 caller 走 None/False 软降级。
    """
    try:
        import ldap3  # type: ignore[import-not-found]

        return ldap3
    except ImportError:
        return None


def _tls_enabled(url: str) -> bool:
    """H4：判定是否启用 TLS——ldaps:// scheme 或 KYLIN_LDAP_USE_TLS=true 任一即开。

    真模式 bind 口令（service 账号 KYLIN_LDAP_BIND_PASSWORD）不能明文过网。
    """
    if url.lower().startswith("ldaps://"):
        return True
    return os.environ.get("KYLIN_LDAP_USE_TLS", "false").strip().lower() == "true"


def _build_server(ldap3: Any, url: str) -> Any:
    """H4：构建 ldap3.Server，按需启用 TLS（use_ssl + 证书校验 CERT_REQUIRED）。

    启用条件见 _tls_enabled。证书校验默认 CERT_REQUIRED（生产要求真校验），
    证书链/CA 配置在部署文档说明（KYLIN_LDAP_CA_CERT 可选指定 CA bundle）。
    """
    if _tls_enabled(url):
        ca_cert = os.environ.get("KYLIN_LDAP_CA_CERT", "").strip() or None
        tls = ldap3.Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=ca_cert)
        return ldap3.Server(
            url,
            connect_timeout=5,
            get_info=ldap3.NONE,
            use_ssl=True,
            tls=tls,
        )
    return ldap3.Server(
        url,
        connect_timeout=5,
        get_info=ldap3.NONE,
    )


@dataclass
class LdapUser:
    username: str
    display_name: str
    groups: list[str]
    roles: list[str]


class LdapClient:
    def __init__(self) -> None:
        self.mock = os.environ.get("KYLIN_LDAP_MOCK", "false").lower() == "true"
        self._group_role_map = _parse_group_role_map(os.environ.get("KYLIN_LDAP_GROUP_ROLE_MAP"))
        # 真模式配置在 __init__ 时一次性读取并校验（P1b #4 必填 env 检查）。
        # 缺失不抛——给 caller 软降级机会（proxy_basic_auth 可走"LDAP 不可用"分支）。
        self._real_cfg: dict[str, str] = {}
        if not self.mock:
            for k in _REQUIRED_REAL_ENV:
                v = os.environ.get(k, "").strip()
                if not v:
                    self._real_cfg = {}  # 标记为未配置
                    break
                self._real_cfg[k] = v

    def _bind_user(self, ldap3: Any, username: str, password: str) -> bool:
        """真模式：bind as service account → search user DN → re-bind as user。

        任何步骤失败返 False（不区分"用户不存在" vs "密码错"——防 enumeration）。
        """
        # H3 空口令绕过防护：空/None 口令直接拒。RFC 4513 下很多 LDAP server 允许
        # unauthenticated bind（空口令 bind 返 success），ldap3 auto_bind 会误判为认证通过。
        if not password:
            return False
        if not self._real_cfg:
            return False
        cfg = self._real_cfg
        escaped_user = _escape_ldap_filter(username)
        user_filter = cfg["KYLIN_LDAP_USER_FILTER"].format(escaped_user)
        server = _build_server(ldap3, cfg["KYLIN_LDAP_URL"])
        conn: Any = None
        try:
            conn = ldap3.Connection(
                server,
                user=cfg["KYLIN_LDAP_BIND_DN"],
                password=cfg["KYLIN_LDAP_BIND_PASSWORD"],
                auto_bind=True,
                receive_timeout=5,
            )
            # service 账号 bind OK → search user DN
            conn.search(
                search_base=cfg["KYLIN_LDAP_BASE_DN"],
                search_filter=user_filter,
                search_scope=ldap3.SUBTREE,
                size_limit=1,
                attributes=[cfg["KYLIN_LDAP_GROUP_ATTR"], "cn"],
            )
            if not conn.entries:
                return False
            user_dn = str(conn.entries[0].entry_dn)
            # 用 user DN + password 试 bind——失败 = 凭据错（不区分用户存不存在）
            user_conn = ldap3.Connection(
                server,
                user=user_dn,
                password=password,
                auto_bind=True,
                receive_timeout=5,
            )
            user_conn.unbind()
            return True
        except Exception:  # noqa: BLE001  # 异常吞掉不抛——不暴露 LDAP server 状态
            return False
        finally:
            if conn is not None:
                try:
                    conn.unbind()
                except Exception:  # noqa: BLE001
                    pass

    def _search_user_attrs(self, ldap3: Any, username: str) -> dict[str, Any] | None:
        """真模式：bind as service account → search user → 拿 cn + memberOf。

        失败返 None（与 mock 模式 get_user 返 None 同语义）。
        """
        if not self._real_cfg:
            return None
        cfg = self._real_cfg
        escaped_user = _escape_ldap_filter(username)
        user_filter = cfg["KYLIN_LDAP_USER_FILTER"].format(escaped_user)
        server = _build_server(ldap3, cfg["KYLIN_LDAP_URL"])
        conn: Any = None
        try:
            conn = ldap3.Connection(
                server,
                user=cfg["KYLIN_LDAP_BIND_DN"],
                password=cfg["KYLIN_LDAP_BIND_PASSWORD"],
                auto_bind=True,
                receive_timeout=5,
            )
            conn.search(
                search_base=cfg["KYLIN_LDAP_BASE_DN"],
                search_filter=user_filter,
                search_scope=ldap3.SUBTREE,
                size_limit=1,
                attributes=[cfg["KYLIN_LDAP_GROUP_ATTR"], "cn"],
            )
            if not conn.entries:
                return None
            entry = conn.entries[0]
            display_name = str(entry.cn) if "cn" in entry else username
            group_attr_name = cfg["KYLIN_LDAP_GROUP_ATTR"]
            if group_attr_name in entry:
                groups = [str(g) for g in entry[group_attr_name].values]
            else:
                groups = []
            return {"display_name": display_name, "groups": groups}
        except Exception:  # noqa: BLE001
            return None
        finally:
            if conn is not None:
                try:
                    conn.unbind()
                except Exception:  # noqa: BLE001
                    pass

    def authenticate(self, username: str, password: str) -> bool:
        """
        Verify username/password against LDAP.
        Mock mode: accept only known users with password "kylin123" (demo only).
        Real mode: bind as service account → search user DN → re-bind as user.
        """
        # H3 空口令绕过防护：mock/真模式入口一律拒空口令，保持行为一致。
        if not password:
            return False
        if self.mock:
            entry = _MOCK_USERS.get(username)
            if entry is None:
                return False
            return entry[0] == password
        # 真模式
        ldap3 = _import_ldap3()
        if ldap3 is None:
            return False
        return self._bind_user(ldap3, username, password)

    def get_user(self, username: str) -> LdapUser | None:
        """
        Fetch user info including groups and mapped roles.
        Mock mode: return hardcoded test users.
        Real mode: bind as service account → search user → map groups → roles.
        """
        if self.mock:
            entry = _MOCK_USERS.get(username)
            if entry is None:
                return None
            _password, display_name, groups = entry
            roles = [
                role
                for group in groups
                if (
                    role := self._group_role_map.get(_normalize_group_name(group))
                    or self._group_role_map.get(group)
                )
                is not None
            ]
            return LdapUser(
                username=username,
                display_name=display_name,
                groups=groups,
                roles=roles,
            )
        # 真模式
        ldap3 = _import_ldap3()
        if ldap3 is None:
            return None
        attrs = self._search_user_attrs(ldap3, username)
        if attrs is None:
            return None
        roles = [
            role
            for group in attrs["groups"]
            if (
                role := self._group_role_map.get(_normalize_group_name(group))
                or self._group_role_map.get(group)
            )
            is not None
        ]
        return LdapUser(
            username=username,
            display_name=attrs["display_name"],
            groups=attrs["groups"],
            roles=roles,
        )
