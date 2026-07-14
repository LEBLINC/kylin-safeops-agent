"""A2.1: WebSocket 反代 sidecar，真接 LDAP（wsproxy vs proxy.py 的 WS 版）.

proxy.py 是 HTTP(S)/SSE 反代；本模块是 WebSocket 透传反代——浏览器 WS 连接经此
sidecar 校验 Basic Auth（真接 LDAP，ldap_client.authenticate/get_user）后，
携签名 X-Auth-* v2 4 头转发到上游 app 的 WS 端点。签名口径与 proxy.py 字节级
一致（同一 _sign.py 公共 helper），保证 backend/app/api/auth.py::verify_proxy_identity
校验通过。

握手鉴权逻辑抽成纯函数 `authenticate_and_build_headers`，与 FastAPI WebSocket
协议解耦——便于单测直接验证鉴权分支，不依赖 `websockets` 包起真实 WS 连接。
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
import uuid

from deploy.proxy._sign import STRIP_HEADERS, sign
from deploy.sso.ldap_client import LdapClient

UPSTREAM_WS = os.environ.get("KYLIN_UPSTREAM_WS", "ws://127.0.0.1:8000")


def _parse_basic_auth(auth_header: str) -> tuple[str, str] | None:
    """解析 ``Authorization: Basic <b64>`` → (username, password)；不合法返回 None."""
    if not auth_header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(auth_header[6:]).decode()
        username, password = decoded.split(":", 1)
    except Exception:  # noqa: BLE001  # 解码失败即视为鉴权失败，不暴露细节
        return None
    return username, password


def authenticate_and_build_headers(
    ldap_client: LdapClient,
    auth_header: str,
    *,
    method: str,
    path: str,
    body: bytes = b"",
    raw_headers: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """WS 握手鉴权核心逻辑：Basic Auth → 真接 LDAP → 签名 4 头。

    成功返回**已剥离客户端伪造头 + 注入签名 4 头**的完整转发头字典；
    任一步失败（Basic Auth 缺失/解码失败/LDAP 认证失败/用户不存在）返回 None
    （caller 据此对 WS 握手回 401/拒绝 accept，fail-closed）。
    """
    parsed = _parse_basic_auth(auth_header)
    if parsed is None:
        return None
    username, password = parsed
    if not ldap_client.authenticate(username, password):
        return None
    ldap_user = ldap_client.get_user(username)
    if ldap_user is None:
        return None

    user = ldap_user.username
    roles = ",".join(ldap_user.roles)
    headers = {
        k: v
        for k, v in (raw_headers or {}).items()
        if k.lower() not in STRIP_HEADERS and k.lower() != "host"
    }
    ts = str(int(time.time()))
    body_sha = hashlib.sha256(body or b"").hexdigest()
    nonce = uuid.uuid4().hex
    headers.update(
        {
            "X-Auth-User": user,
            "X-Auth-Roles": roles,
            "X-Auth-Timestamp": ts,
            "X-Auth-Signature": sign(user, roles, ts, method, path, body_sha, nonce),
            "X-Auth-Method": method,
            "X-Auth-Path": path,
            "X-Auth-Body-Sha": body_sha,
            "X-Auth-Nonce": nonce,
        }
    )
    return headers
