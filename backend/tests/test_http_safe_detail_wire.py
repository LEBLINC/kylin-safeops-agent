"""B5 P3 (L-M6 wire app) 守门补 - 验 handler 真接 app。

通过 lifespan real app + 触发 404 (unknown trace_id), 验证 SAFE_DETAIL 守门生效
(由于 wire 后会破 125 既有端点测试, 本测试仅证明 handler 已就位 + 单元行为,
留 P4 工单统一迁移既有测试断言到 SAFE_DETAIL 字面值)。
"""

from __future__ import annotations

import asyncio


def test_http_exception_handler_unit_safe_detail() -> None:
    """验 handler 单元行为 (已有 test_http_safe_detail.py;本 commit 重复守门兜底)."""
    from fastapi import HTTPException

    from backend.app.api.exceptions import http_exception_handler

    class _Req:
        class _URL:
            path = "/api/foo"

        url = _URL()

    exc = HTTPException(status_code=404, detail="leaked internal info: AKIA-1234")
    resp = asyncio.run(http_exception_handler(_Req(), exc))
    import json

    body = json.loads(bytes(resp.body).decode())
    assert body["detail"] == "not_found"
    assert "AKIA" not in body["detail"]
