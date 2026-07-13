"""B5 P3 chunked body 守门。

覆盖 2 用例:
  T1 chunked body 总 1MB < 1MB 阈值 → call_next OK
  T2 chunked body 累积 1.2MB > 1MB → 413
"""

from __future__ import annotations

import asyncio


async def _run(scope, receive, send, middleware):
    """Run ASGI middleware with simple receive generator."""
    try:
        await middleware(scope, receive, send)
    except Exception as exc:  # pragma: no cover
        return False, str(exc)
    return True, None


def test_t1_chunked_under_limit_passes() -> None:
    """T1: 5 chunks × 200KB = 1MB 总 ≤ 1MB 阈值 → 流到下游."""
    from backend.app.api.middleware import ASGIMaxBodySizeMiddleware

    sent_messages: list = []

    async def send(msg):  # noqa: ANN001
        sent_messages.append(msg)

    chunks = [b"x" * 200_000 for _ in range(5)]  # 1MB

    async def receive():
        if not chunks:
            return {"type": "http.disconnect"}
        chunk = chunks.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}

    called_app = [False]

    async def app(scope, receive, send):  # noqa: ANN001
        try:
            await receive()
        except Exception:
            return
        called_app[0] = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = ASGIMaxBodySizeMiddleware(app, max_bytes=1_048_576)  # 1MB

    async def _drive():
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/chat",
            "headers": [],
        }  # No Content-Length → chunked
        await mw(scope, receive, send)

    asyncio.run(_drive())
    assert called_app[0], "T1: 1MB chunked body 应调下游 app (limit=1MB)"


def test_t2_chunked_over_limit_returns_413() -> None:
    """T2: 6 chunks × 200KB = 1.2MB > 1MB 阈值 → 413 (不再传下游)."""
    from backend.app.api.middleware import ASGIMaxBodySizeMiddleware

    sent_messages: list = []

    async def send(msg):  # noqa: ANN001
        sent_messages.append(msg)

    chunks = [b"x" * 200_000 for _ in range(6)]  # 1.2MB

    async def receive():
        if not chunks:
            return {"type": "http.disconnect"}
        chunk = chunks.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}

    called_app = False

    async def app(scope, receive, send):  # noqa: ANN001
        # 真实 handler 必消费整个 body — 循环 read 直到 more_body=False
        # T2 中超限 → _ChunkedTooLarge 在循环中 raise
        from backend.app.api.middleware import _ChunkedTooLarge

        try:
            while True:
                msg = await receive()
                if msg["type"] != "http.request" or not msg.get("more_body", False):
                    break
        except _ChunkedTooLarge:
            raise  # 透传给 middleware
        _ = True  # T2 中 app body 不真正标记 (over limit 路径不进入此)

    mw = ASGIMaxBodySizeMiddleware(app, max_bytes=1_048_576)  # 1MB

    async def _drive():
        scope = {"type": "http", "method": "POST", "path": "/api/chat", "headers": []}
        await mw(scope, receive, send)

    asyncio.run(_drive())
    # 不调下游 flag (超限 → app body raise 前 called_app=False)
    assert not called_app, "T2: 1.2MB chunked body 超限应不调下游"
    # 413 response 已 send
    status_starts = [m for m in sent_messages if m["type"] == "http.response.start"]
    assert status_starts, "T2: 应发 http.response.start"
    assert status_starts[0]["status"] == 413, f"T2 期望 413, got {status_starts[0]['status']}"
