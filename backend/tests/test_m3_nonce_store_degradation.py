"""之七十五 M-3: Redis nonce store 降级必须留痕（ERROR 级）。

语义后果说明为何这条日志是安全项而非运维便利：
调用方设 KYLIN_NONCE_STORE=redis 即已**显式声明**这是多副本部署。构造失败后
fail-soft 回退到进程内 InMemoryNonceStore，nonce 便只在单副本内唯一——同一个
已签名请求可以在副本 A 用过之后再到副本 B 重放一次，跨副本重放防护静默失效。
服务此时照常返回 200，无日志则运维完全无从察觉这一安全能力降级。

  M3-1 redis 构造失败 → ERROR 级日志 + 回退 InMemoryNonceStore（服务不崩）
  M3-2 日志内容必须点明后果（含"重放"字样）+ 带 exc_info 便于定位根因
  M3-3 memory 模式（未 opt-in redis）不得产生该 ERROR（避免噪音）
"""

from __future__ import annotations

import logging

from backend.app.api import auth as auth_mod


def test_m3_1_degradation_logs_error_and_falls_back(monkeypatch, caplog) -> None:
    """M3-1: 显式要求 redis 但构造失败 → ERROR 日志 + 回退内存实现。"""
    monkeypatch.setenv("KYLIN_NONCE_STORE", "redis")

    def _boom() -> None:
        raise RuntimeError("redis unreachable")

    # 让 RedisNonceStore 的导入路径抛错（模拟依赖缺失/连接失败）
    monkeypatch.setattr(
        auth_mod,
        "_build_redis_nonce_store",
        auth_mod._build_redis_nonce_store,  # 保留真实实现
    )
    import sys

    monkeypatch.setitem(sys.modules, "backend.app.api._redis_nonce_store", None)

    with caplog.at_level(logging.ERROR, logger=auth_mod.__name__):
        store = auth_mod._build_redis_nonce_store()

    assert isinstance(store, auth_mod.InMemoryNonceStore), "M3-1: 应 fail-soft 回退内存实现"
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "M3-1: 降级必须留 ERROR 级日志（此前完全静默）"


def test_m3_2_log_states_consequence_and_carries_traceback(monkeypatch, caplog) -> None:
    """M3-2: 日志须点明"重放防护失效"这一后果，并带 exc_info 便于定位根因。"""
    monkeypatch.setenv("KYLIN_NONCE_STORE", "redis")
    import sys

    monkeypatch.setitem(sys.modules, "backend.app.api._redis_nonce_store", None)

    with caplog.at_level(logging.ERROR, logger=auth_mod.__name__):
        auth_mod._build_redis_nonce_store()

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors
    rec = errors[0]
    assert (
        "重放" in rec.getMessage()
    ), "M3-2: 日志须说明后果（跨副本重放防护失效），仅说'降级'不足以让运维判断严重性"
    assert rec.exc_info is not None, "M3-2: 应带 exc_info，否则无法定位是依赖缺失还是连接失败"


def test_m3_3_memory_mode_is_quiet(monkeypatch, caplog) -> None:
    """M3-3: 未 opt-in redis（默认 memory）不得产生该 ERROR——避免日志噪音。"""
    monkeypatch.delenv("KYLIN_NONCE_STORE", raising=False)

    with caplog.at_level(logging.ERROR, logger=auth_mod.__name__):
        store = auth_mod._build_nonce_store()

    assert isinstance(store, auth_mod.InMemoryNonceStore)
    assert not [
        r for r in caplog.records if r.levelno >= logging.ERROR
    ], "M3-3: memory 是正常默认路径，不应报 ERROR"
