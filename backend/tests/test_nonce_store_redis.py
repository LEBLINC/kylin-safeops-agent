"""A1 P4.2: RedisNonceStore 守门测试（3 用例 T3-T5）.

T3 test_redis_store_replay_blocked：mock redis client → seen=True → 视为重放
T4 test_redis_store_record_atomic：record() 调 SETEX 1 次
T5 test_redis_store_unavailable_falls_back_to_memory：redis 连接失败 → fallback InMemoryNonceStore
"""

from __future__ import annotations

from unittest import mock

import pytest

from backend.app.api.auth import InMemoryNonceStore, _build_redis_nonce_store


def _make_store_with_mock_client() -> tuple[object, mock.MagicMock]:
    """构造 RedisNonceStore 但用 mock client 替身，避免真连 redis。"""
    from backend.app.api._redis_nonce_store import RedisNonceStore

    mock_client = mock.MagicMock()
    with mock.patch.object(RedisNonceStore, "__init__", lambda self: None):
        store = RedisNonceStore()
    store._client = mock_client  # type: ignore[attr-defined]
    return store, mock_client


def test_t3_redis_store_replay_blocked() -> None:
    """T3: mock redis EXISTS 返 True → seen() 报已见过（重放场景）."""
    store, mock_client = _make_store_with_mock_client()
    mock_client.exists.return_value = 1
    assert store.seen("dup-nonce", 1700000000.0) is True, "T3: EXISTS=1 应判定 seen=True (防重放)"
    mock_client.exists.assert_called_once_with("dup-nonce")


def test_t4_redis_store_record_atomic() -> None:
    """T4: record() 恰好调 1 次 SETEX (key=nonce, ttl=300, value=timestamp)."""
    store, mock_client = _make_store_with_mock_client()
    store.record("n-atomic", 1700000000.0)
    mock_client.setex.assert_called_once_with("n-atomic", 300, "1700000000.0")


def test_t5_redis_store_unavailable_falls_back_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """T5: redis 连接/依赖不可用 (RuntimeError) → _build_redis_nonce_store fallback 内存实现."""
    monkeypatch.setattr(
        "backend.app.api._redis_nonce_store.RedisNonceStore.__init__",
        lambda self: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
    )
    store = _build_redis_nonce_store()
    assert isinstance(
        store, InMemoryNonceStore
    ), f"T5: redis 不可用应 fail-soft 回退 InMemoryNonceStore, got {type(store)!r}"
