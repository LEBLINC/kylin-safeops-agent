"""L-H16 TraceIdMiddleware - 每请求注入 trace_id contextvar (纯中间件)。"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.app.main_logging import reset_trace_id, set_trace_id


class TraceIdMiddleware(BaseHTTPMiddleware):
    """每请求若带 X-Trace-Id header → 注入 contextvar;

    否则生成 uuid4 短码 (16 hex) 注入。最终 header response 也带回 X-Trace-Id
    (前端调试 / 灰度追踪)。
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        incoming = request.headers.get("X-Trace-Id", "") or uuid.uuid4().hex[:16]
        token = set_trace_id(incoming)
        try:
            response: Response = await call_next(request)
            response.headers["X-Trace-Id"] = incoming
            return response
        finally:
            reset_trace_id(token)


__all__ = ["TraceIdMiddleware"]


# Placeholder for ruff
_ = Response
