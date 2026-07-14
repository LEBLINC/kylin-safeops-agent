"""A2.1: v2 签名公共 helper（proxy.py + wsproxy.py 共用，杜绝重复实现漂移）.

抽自 proxy.py 原 _secret()/sign()/STRIP_HEADERS —— HTTP 反代与 WebSocket 反代
的签名口径必须字节级一致（同一 backend/app/api/auth.py::verify_proxy_identity
校验），故抽公共模块而非各自重复写一份。
"""

from __future__ import annotations

import hashlib
import hmac
import os

#: 反代注入的签名头 + 客户端可能伪造的裸角色头：转发前必须剥离，防止客户端越权注入。
STRIP_HEADERS = {
    "x-auth-user",
    "x-auth-roles",
    "x-auth-timestamp",
    "x-auth-signature",
    "x-auth-method",
    "x-auth-path",
    "x-auth-body-sha",
    "x-auth-nonce",
    "x-user-role",
}


def get_secret() -> str:
    """每次读 env（不模块级 capture），避免 monkeypatch 在测试里失效。"""
    return os.environ["KYLIN_PROXY_AUTH_SECRET"]


def sign(
    user: str,
    roles: str,
    ts: str,
    method: str = "",
    path: str = "",
    body_sha: str = "",
    nonce: str = "",
) -> str:
    """v2 签名：method/path/body_sha/nonce 全部入串（防中途篡改 + 防重放）.

    canonical 口径须与 backend/app/api/auth.py::_canonical 字节级一致。
    """
    canonical = f"{user}\n{roles}\n{ts}\n{method}\n{path}\n{body_sha}\n{nonce}"
    return hmac.new(get_secret().encode(), canonical.encode(), hashlib.sha256).hexdigest()
