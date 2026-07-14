"""RedisNonceStore（A1 P4.2）：跨进程 nonce 防重放存储，multi-replica 部署用。

实现 auth.py::NonceStore Protocol。redis 是可选运行时依赖——未安装包 /
未配置 KYLIN_REDIS_URL / 连接失败时，本模块 __init__ 直接抛异常，交由
auth.py::_build_redis_nonce_store() 的 try/except 捕获并 fail-soft 回退
InMemoryNonceStore（不炸进程；与 ldap_client.py::_import_ldap3 同一模式）。
"""

from __future__ import annotations

import os
from typing import Any

#: Redis 连接串环境变量；multi-replica 部署必设（未设即构造失败→回退内存实现）。
_REDIS_URL_ENV = "KYLIN_REDIS_URL"

#: nonce key 过期秒数，与 auth.py::_MAX_CLOCK_SKEW_SECONDS 防重放窗口对齐。
_TTL_SECONDS = 300


def _import_redis() -> Any | None:
    """延迟 import redis——未装包时返回 None（不炸进程，交给 caller 软降级）。"""
    try:
        import redis  # type: ignore[import-untyped]

        return redis
    except ImportError:
        return None


class RedisNonceStore:
    """Redis 后端 nonce store：SETEX 写入 + EXISTS 查询，跨进程/跨副本共享状态。

    TTL 由 Redis 自身到期淘汰（gc() 因此是 no-op，仅为满足 Protocol 接口一致性）。
    """

    def __init__(self) -> None:
        redis_mod = _import_redis()
        if redis_mod is None:
            raise RuntimeError("redis package not installed")
        url = os.environ.get(_REDIS_URL_ENV)
        if not url:
            raise RuntimeError(f"{_REDIS_URL_ENV} not configured")
        self._client = redis_mod.from_url(url)

    def seen(self, nonce: str, now: float) -> bool:
        return bool(self._client.exists(nonce))

    def record(self, nonce: str, now: float) -> None:
        self._client.setex(nonce, _TTL_SECONDS, str(now))

    def gc(self, now: float) -> None:
        """Redis TTL 自动过期已覆盖清理语义，此处 no-op（保留 Protocol 接口一致）。"""
        return None
