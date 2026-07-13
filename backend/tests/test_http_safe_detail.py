"""B5 commit 3 L-M6: HTTPException safe detail handler 守门。

T1: 直接调 http_exception_handler,验证响应 detail 走 SAFE_DETAIL 不含原文。
"""

from __future__ import annotations

import asyncio


def test_http_exception_safe_detail() -> None:
    """T1: HTTPException(detail="traceback internals") → 响应 detail 不含原文."""
    from fastapi import HTTPException

    from backend.app.api.exceptions import http_exception_handler

    class _Req:
        class _URL:
            path = "/api/audit/traces/abc"

        url = _URL()

    exc = HTTPException(status_code=404, detail="internal_secret_key=AKIA-1234 leaked")
    resp = asyncio.run(http_exception_handler(_Req(), exc))
    assert resp.status_code == 404
    import json

    body = json.loads(bytes(resp.body).decode())
    assert body["detail"] == "not_found"
    assert "AKIA" not in body["detail"]
    assert "leaked" not in body["detail"]
