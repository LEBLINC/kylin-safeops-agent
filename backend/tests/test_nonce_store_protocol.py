"""A1 P4.1: NonceStore Protocol 抽象 + InMemoryNonceStore 守门测试.

覆盖 2 用例:
  T1 同 nonce 第二次 verify (经 InMemoryNonceStore) → None (防重放)
  T2 gc() 推进 300s+ 后过期 nonce 被清除 (seen 变 False)
"""

from __future__ import annotations

from backend.app.api.auth import InMemoryNonceStore


def test_t1_inmemory_store_replay_blocked() -> None:
    """T1: 同 nonce 记录后第二次 seen() → True (verify_proxy_identity 借此判重放)."""
    store = InMemoryNonceStore()
    now = 1700000000.0
    assert store.seen("n1", now) is False, "T1: 首次 seen 应 False (未记录)"
    store.record("n1", now)
    assert store.seen("n1", now) is True, "T1: record 后同 nonce 第二次 seen 应 True (防重放)"


def test_t2_inmemory_store_gc_clears_expired() -> None:
    """T2: gc() 推进 301s 后过期 nonce 被清除 → seen 变 False."""
    store = InMemoryNonceStore()
    now = 1700000000.0
    store.record("n2", now)
    assert store.seen("n2", now) is True, "T2: record 后应 seen"
    later = now + 301.0
    store.gc(later)
    assert store.seen("n2", later) is False, "T2: gc 推进 301s 后过期 nonce 应被清除 (seen False)"
