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


def _canonical(user: str, roles: str, timestamp: str) -> str:
    """签名规范串：user\\nroles\\ntimestamp（roles 用头原值，不归一）。"""
    return f"{user}\n{roles}\n{timestamp}"


def sign_identity(user: str, roles_csv: str, timestamp: str | int, secret: str) -> str:
    """生成 X-Auth-Signature（参考实现 + 测试用 + 反代签名口径）。

    返回 hex(HMAC_SHA256(secret, canonical))。
    """
    canonical = _canonical(user, roles_csv, str(timestamp))
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_proxy_identity(
    *,
    user: str | None,
    roles: str | None,
    timestamp: str | None,
    signature: str | None,
    now: float | None = None,
) -> Principal | None:
    """验证反代签名身份；**fail-closed**——任一不满足即返回 None。

    拒绝条件：密钥未配置 / 任一头缺失或空 / 时间戳非法或超窗（防重放）/ HMAC 不匹配。
    通过 → Principal(user, frozenset(小写 roles))。HMAC 用 hmac.compare_digest 常量时间比较。
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
    expected = sign_identity(user, roles, timestamp, secret)
    if not hmac.compare_digest(expected, signature):
        return None
    role_set = frozenset(r.strip().lower() for r in roles.split(",") if r.strip())
    return Principal(user=user, roles=role_set)
