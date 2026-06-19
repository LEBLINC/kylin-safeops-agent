"""
LDAP authentication client for Kylin SafeOps proxy sidecar.
Supports mock mode (hardcoded test users) and real LDAP server (ldap3 Server + Connection).

Env vars:
  KYLIN_LDAP_MOCK=true|false        — default false, mock mode bypasses real server
  KYLIN_LDAP_URL=ldap://...         — real LDAP server URL (required when mock=false)
  KYLIN_LDAP_BIND_DN=cn=...         — service account bind DN
  KYLIN_LDAP_BIND_PASSWORD=...      — service account password (NEVER in repo)
  KYLIN_LDAP_BASE_DN=dc=...         — base DN for user/group search
  KYLIN_LDAP_USER_FILTER=(uid={})   — filter template for user lookup, {} = username
  KYLIN_LDAP_GROUP_ATTR=memberOf    — LDAP attribute for group membership
  KYLIN_LDAP_GROUP_ROLE_MAP=...     — JSON: {"kylin-admins":"admin","kylin-ops":"operator",...}
"""

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional


_DEFAULT_GROUP_ROLE_MAP: Dict[str, str] = {
    "kylin-admins": "admin",
    "kylin-ops": "operator",
    "kylin-auditors": "auditor",
    "kylin-viewers": "viewer",
}

_MOCK_USERS: Dict[str, tuple] = {
    "admin": ("kylin123", "Admin User", ["kylin-admins", "kylin-ops"]),
    "operator": ("kylin123", "Operator User", ["kylin-ops"]),
    "auditor": ("kylin123", "Auditor User", ["kylin-auditors"]),
    "viewer": ("kylin123", "Viewer User", ["kylin-viewers"]),
}


def _parse_group_role_map(raw: Optional[str]) -> Dict[str, str]:
    if raw is None:
        return dict(_DEFAULT_GROUP_ROLE_MAP)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return dict(_DEFAULT_GROUP_ROLE_MAP)


@dataclass
class LdapUser:
    username: str
    display_name: str
    groups: List[str]
    roles: List[str]


class LdapClient:
    def __init__(self) -> None:
        self.mock = os.environ.get("KYLIN_LDAP_MOCK", "false").lower() == "true"
        self._group_role_map = _parse_group_role_map(
            os.environ.get("KYLIN_LDAP_GROUP_ROLE_MAP")
        )

    def authenticate(self, username: str, password: str) -> bool:
        """
        Verify username/password against LDAP.
        Mock mode: accept only known users with password "kylin123" (demo only).
        Real mode: bind as user DN to verify credentials.
        """
        if self.mock:
            entry = _MOCK_USERS.get(username)
            if entry is None:
                return False
            return entry[0] == password
        # TODO: real LDAP bind via ldap3 Server + Connection
        raise NotImplementedError

    def get_user(self, username: str) -> Optional[LdapUser]:
        """
        Fetch user info including groups and mapped roles.
        Mock mode: return hardcoded test users.
        Real mode: search LDAP for user entry, read group_attr, map to roles.
        """
        if self.mock:
            entry = _MOCK_USERS.get(username)
            if entry is None:
                return None
            _password, display_name, groups = entry
            roles = [
                role
                for group in groups
                if (role := self._group_role_map.get(group)) is not None
            ]
            return LdapUser(
                username=username,
                display_name=display_name,
                groups=groups,
                roles=roles,
            )
        # TODO: real LDAP search via ldap3
        raise NotImplementedError
