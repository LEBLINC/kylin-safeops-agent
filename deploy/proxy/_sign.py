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


#: 占位密钥前缀（与 backend/app/api/auth.py 同口径）。install.sh 写 env 骨架时的
#: `CHANGE_ME_...` 是仓库内公开字符串——反代若用它签名，任何人都能伪造出 app 端
#: 验签通过的身份头。故视同未配置，与"未设 env"同样 fail-fast。
_PLACEHOLDER_PREFIX = "CHANGE_ME"


def get_secret() -> str:
    """每次读 env（不模块级 capture），避免 monkeypatch 在测试里失效。

    未配置或仍为占位值 → KeyError/RuntimeError，让反代**起不来**而不是用公开
    常量对外签名（起不来是可见故障，裸奔签名是静默的认证失效）。
    """
    secret = os.environ["KYLIN_PROXY_AUTH_SECRET"]
    if secret.strip().startswith(_PLACEHOLDER_PREFIX):
        raise RuntimeError(
            "KYLIN_PROXY_AUTH_SECRET 仍为占位值（CHANGE_ME...）：该串是仓库内公开常量，"
            "用它签名等于任何人都能伪造身份。请用 `openssl rand -hex 32` 生成真值后填入 "
            "/etc/kylin/proxy.env，并与 app 侧 /etc/kylin-safeops/agent.env 保持一致。"
        )
    return secret


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
