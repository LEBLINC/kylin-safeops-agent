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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

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


class NonceStore(Protocol):
    """nonce 防重放存储抽象（A1 P4）：解耦单进程 dict 与 multi-replica 共享后端.

    ``seen``：nonce 是否已见过（不改变状态）；``record``：验签通过后记录 nonce
    （幂等，可重复调）；``gc``：清理过期项（防内存/存储无界增长）。
    """

    def seen(self, nonce: str, now: float) -> bool: ...  # noqa: D102

    def record(self, nonce: str, now: float) -> None: ...  # noqa: D102

    def gc(self, now: float) -> None: ...  # noqa: D102


class InMemoryNonceStore:
    """单进程 in-process dict 实现（A1.2 原实现迁移；dev 默认，KYLIN_NONCE_STORE=memory）.

    nonce → 入池时间戳；超出 _NONCE_MAX 按插入顺序 FIFO 淘汰最旧项防无界增长。
    """

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}
        self._max = 4096

    def seen(self, nonce: str, now: float) -> bool:
        return nonce in self._seen

    def record(self, nonce: str, now: float) -> None:
        self._seen[nonce] = now
        while len(self._seen) > self._max:
            oldest = next(iter(self._seen))
            self._seen.pop(oldest, None)

    def gc(self, now: float) -> None:
        """清理超出 _MAX_CLOCK_SKEW_SECONDS 窗口的 nonce (防内存泄漏)."""
        expired = [n for n, ts in self._seen.items() if abs(now - ts) > _MAX_CLOCK_SKEW_SECONDS]
        for n in expired:
            self._seen.pop(n, None)


#: nonce store 后端选择环境变量；默认 memory（dev 单进程）。
_NONCE_STORE_ENV = "KYLIN_NONCE_STORE"

#: 进程内单例（延迟构造；测试可通过 _reset_nonce_store_for_tests 重置）。
_nonce_store_singleton: NonceStore | None = None


def _build_nonce_store() -> NonceStore:
    """按 KYLIN_NONCE_STORE 构造对应后端；未知值 / 未配置一律回退 memory."""
    backend_name = os.environ.get(_NONCE_STORE_ENV, "memory").strip().lower()
    if backend_name == "redis":
        return _build_redis_nonce_store()
    return InMemoryNonceStore()


def _build_redis_nonce_store() -> NonceStore:
    """构造 RedisNonceStore；导入或连接失败时 fail-soft 回退 InMemoryNonceStore.

    生产 multi-replica 部署应显式设 KYLIN_REDIS_URL；dev 缺省已由 KYLIN_NONCE_STORE
    默认值 memory 兜底，本函数只在显式 opt-in redis 时才被调。
    """
    try:
        from backend.app.api._redis_nonce_store import RedisNonceStore

        return RedisNonceStore()
    except Exception:  # noqa: BLE001  # 连接/依赖不可用不炸进程，退回内存实现
        return InMemoryNonceStore()


def _get_nonce_store() -> NonceStore:
    """取进程内 nonce store 单例（延迟构造，读一次 env）."""
    global _nonce_store_singleton
    if _nonce_store_singleton is None:
        _nonce_store_singleton = _build_nonce_store()
    return _nonce_store_singleton


def _reset_nonce_store_for_tests(store: NonceStore | None = None) -> None:
    """测试专用：重置/替换单例（跨用例隔离状态，避免 nonce 残留互相影响）."""
    global _nonce_store_singleton
    _nonce_store_singleton = store


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
    canonical = _canonical(
        user, roles_csv, str(timestamp), method=method, path=path, body_sha=body_sha, nonce=nonce
    )
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
        user,
        roles,
        timestamp,
        secret,
        method=method,
        path=path,
        body_sha=body_sha,
        nonce=nonce,
    )
    if not hmac.compare_digest(expected, signature):
        return None
    # A1 P4: nonce 防重放改用可插拔 NonceStore（原 in-process dict 迁至 InMemoryNonceStore，
    # multi-replica 部署可切 KYLIN_NONCE_STORE=redis 跨进程共享）。
    store = _get_nonce_store()
    if nonce and store.seen(nonce, current):
        return None
    role_set = frozenset(r.strip().lower() for r in roles.split(",") if r.strip())
    # 验签通过 → 记录 nonce (仅当 nonce 非空; v1 fixture 测空 nonce 仍 PASS)
    if nonce:
        store.record(nonce, current)
    if record_nonce is not None:
        record_nonce(nonce)
    return Principal(user=user, roles=role_set)
