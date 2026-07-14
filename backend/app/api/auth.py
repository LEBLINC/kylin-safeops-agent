"""可信反向代理签名身份契约 + 验证（L 域，决策⑨=方案a）。

定位：消除"裸 X-User-Role 头可伪造"——审批授权的角色必须来自**可信反向代理注入、且 app 能
验证来源真实性的签名头**；fail-closed。本模块只提供纯函数（验签 + 签名参考实现），
FastAPI 依赖接线在 deps.py。

头契约（反代注入；也是给反代/部署文档的签名口径）：
- ``X-Auth-User``：已验证用户名；
- ``X-Auth-Roles``：逗号分隔小写角色（如 ``operator,admin``）；
- ``X-Auth-Timestamp``：Unix 秒（防重放）；
- ``X-Auth-Signature``：``hex(HMAC_SHA256(secret, canonical))``，
  ``canonical = f"{user}\\n{roles}\\n{timestamp}"``（roles 用头原值，不归一）。

密钥 ``KYLIN_PROXY_AUTH_SECRET``：共享密钥，仅可信代理与 app 知道。**未配置即 fail-closed**
（verify 一律返回 None）——安全兜底，不设环境变量则审批闸 proxy 模式拒绝一切。

纪律：纯 stdlib（hmac/hashlib/time），无新依赖；除读 env 外无 IO；常量时间比较防时序侧信道。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass

#: 防重放时间窗（秒）：|now - timestamp| 超过即拒。
_MAX_CLOCK_SKEW_SECONDS = 300

#: 共享密钥环境变量名。
_SECRET_ENV = "KYLIN_PROXY_AUTH_SECRET"


@dataclass(frozen=True)
class Principal:
    """经验证的调用者身份（不可变）。roles 为内部小写角色集合。"""

    user: str
    roles: frozenset[str]


def _get_secret() -> str | None:
    """读取共享密钥（每次读，便于测试 monkeypatch env）；未配置返回 None。"""
    secret = os.environ.get(_SECRET_ENV)
    return secret or None


#: A1.2 nonce LRU 缓存（in-process dict; maxsize + 过期清理）.
#: nonce → 入池时间戳. 同 nonce 第二次 verify 时返 None 防重放.
_SEEN_NONCES: dict[str, float] = {}
_NONCE_MAX = 4096


def _gc_nonces(now: float) -> None:
    """清理超出 _MAX_CLOCK_SKEW_SECONDS 窗口的 nonce (防内存泄漏)."""
    expired = [n for n, ts in _SEEN_NONCES.items() if abs(now - ts) > _MAX_CLOCK_SKEW_SECONDS]
    for n in expired:
        _SEEN_NONCES.pop(n, None)
    # 上限保护
    while len(_SEEN_NONCES) > _NONCE_MAX:
        # 删最旧 (FIFO; dict 保留插入顺序)
        oldest = next(iter(_SEEN_NONCES))
        _SEEN_NONCES.pop(oldest, None)


def _canonical(
    user: str,
    roles: str,
    timestamp: str,
    *,
    method: str = "",
    path: str = "",
    body_sha: str = "",
    nonce: str = "",
) -> str:
    """L-H5 + A1.1 v2 签名规范串.

    Backward compat (L-H5 既有 3 字段签名): 当 method/path/body_sha/nonce 全部为空
    → 返回 v1 (3 字段) 串, 不尾随 4 换行 (避免与既有 conftest fixture + 既有签名客户端不兼容).
    Any v2 field 非空 → v2 7 字段 (含 method/path/body_sha/nonce 防中途篡改+防重放).
    """
    if not (method or path or body_sha or nonce):
        return f"{user}\n{roles}\n{timestamp}"
    return f"{user}\n{roles}\n{timestamp}\n{method}\n{path}\n{body_sha}\n{nonce}"


def sign_identity(
    user: str,
    roles_csv: str,
    timestamp: str | int,
    secret: str,
    *,
    method: str = "",
    path: str = "",
    body_sha: str = "",
    nonce: str = "",
) -> str:
    """生成 X-Auth-Signature (参考实现 + 测试用 + 反代签名口径).

    返回 hex(HMAC_SHA256(secret, canonical)).
    """
    canonical = _canonical(user, roles_csv, str(timestamp), method=method, path=path, body_sha=body_sha, nonce=nonce)
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_proxy_identity(
    *,
    user: str | None,
    roles: str | None,
    timestamp: str | None,
    signature: str | None,
    method: str = "",
    path: str = "",
    body_sha: str = "",
    nonce: str = "",
    now: float | None = None,
    record_nonce: Callable[[str], None] | None = None,
) -> Principal | None:
    """验证反代签名身份;fail-closed——任一不满足即返回 None。

    拒绝条件:密钥未配置 / 任一头缺失或空 / 时间戳非法或超窗 (防重放) /
    HMAC 不匹配。
    通过 → Principal(user, frozenset(小写 roles))。HMAC 用 hmac.compare_digest 常量时间比较。

    A1.1 v2: method/path/body_sha/nonce 全部入串 (防中途篡改 + nonce 防重放).
    A1.2: nonce 一次性 — record_nonce(已使用 nonce 列表) 在 verify 通过后调,
        同 nonce 第二次 verify 时 verify_proxy_identity 返 None (replay block).
    """
    secret = _get_secret()
    if not secret:
        return None
    if not user or not roles or not timestamp or not signature:
        return None
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return None
    current = time.time() if now is None else now
    if abs(current - ts) > _MAX_CLOCK_SKEW_SECONDS:
        return None
    expected = sign_identity(
        user, roles, timestamp, secret,
        method=method, path=path, body_sha=body_sha, nonce=nonce,
    )
    if not hmac.compare_digest(expected, signature):
        return None
    # A1.2: nonce 防重放 — 已用过的 nonce 第二次 verify 直接 None
    if nonce and nonce in _SEEN_NONCES:
        return None
    role_set = frozenset(r.strip().lower() for r in roles.split(",") if r.strip())
    # 验签通过 → 记录 nonce (仅当 nonce 非空; v1 fixture 测空 nonce 仍 PASS)
    if nonce:
        _SEEN_NONCES[nonce] = current
    if record_nonce is not None:
        record_nonce(nonce)
    return Principal(user=user, roles=role_set)
