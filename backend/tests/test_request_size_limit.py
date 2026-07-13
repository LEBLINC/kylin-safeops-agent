"""B5 commit 2 L-M5 RequestSizeLimitMiddleware 守门。

T1 Content-Length 超限 → 413
T2 Content-Length 等于 limit (边界) → 走 call_next
"""

from __future__ import annotations

import asyncio
import json

# ---- T1: Content-Length 超限 → 413 ----


def test_t1_content_length_exceeds_returns_413() -> None:
    """T1: mock request.headers 含 Content-Length=2MB → middleware 返 413 JSONResponse."""
    from fastapi.responses import JSONResponse

    from backend.app.api.middleware import RequestSizeLimitMiddleware

    class _Req:
        headers = {"content-length": str(2 * 1024 * 1024)}  # 2MB

    async def _call_next(req):  # noqa: ANN001
        return {"ok": True}

    mw = RequestSizeLimitMiddleware(app=None)  # type: ignore[arg-type]
    resp = asyncio.run(mw.dispatch(_Req(), _call_next))  # type: ignore[arg-type]
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 413
    body = json.loads(bytes(resp.body).decode())  # type: ignore[attr-defined]
    assert body["detail"] == "request_too_large"


# ---- T2: Content-Length == limit → call_next ----


def test_t2_content_length_at_boundary_calls_next() -> None:
    """T2: Content-Length < limit → 走 call_next."""
    from backend.app.api.middleware import RequestSizeLimitMiddleware

    class _Req:
        headers = {"content-length": "1024"}  # 1KB < 1MB

    called = False

    async def _call_next(req):  # noqa: ANN001
        nonlocal called
        called = True
        return None

    mw = RequestSizeLimitMiddleware(app=None)  # type: ignore[arg-type]
    asyncio.run(mw.dispatch(_Req(), _call_next))  # type: ignore[arg-type]
    assert called, "T2: 不超限应调 call_next"
