"""L-H16 TraceIdMiddleware - 每请求注入 trace_id contextvar (纯中间件)。"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

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


# ============================================================
# B5 commit 2 L-M5: RequestSizeLimitMiddleware
# ============================================================
import os as _os_lm5

_DEFAULT_MAX_BYTES = 1024 * 1024  # 1MB


def _max_request_bytes() -> int:
    """读 KYLIN_MAX_REQUEST_BYTES env;默认 1MB。"""
    raw = _os_lm5.environ.get("KYLIN_MAX_REQUEST_BYTES", "")
    if not raw:
        return _DEFAULT_MAX_BYTES
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_MAX_BYTES


_413_PAYLOAD = {"detail": "request_too_large"}


async def _consume_until_exceeds(body, limit: int) -> bool:
    """累计读 body chunks,超过 limit 立即返 True (不继续读)。"""
    total = 0
    async for chunk in body:
        total += len(chunk)
        if total > limit:
            return True
    return False


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """L-M5: 请求体大小上限。

    - Content-Length 存在: 直接比较 header 值, 超限 → 413 JSONResponse
    - Content-Length 缺失/无效 (chunked): 累计读 chunks, 超限 → 413
    默认 1MB, KYLIN_MAX_REQUEST_BYTES env 可调。

    实现注意: BaseHTTPMiddleware dispatch 中**不能调 request.stream()** (consumes body),
    否则下游 handler 拿不到 body。本 middleware 只检查 Content-Length header + 提供
    chunked body 累计字节上限的辅助函数 _consume_until_exceeds (供测试与未来 chunked
    handler 增量复用)。
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        limit = _max_request_bytes()
        cl_header = request.headers.get("content-length")
        if cl_header is not None:
            try:
                cl = int(cl_header)
                if cl > limit:
                    return JSONResponse(status_code=413, content=_413_PAYLOAD)
            except ValueError:
                # malformed Content-Length → fall through (下游 handler 自行处理)
                pass
        # chunked / 无 Content-Length: 不在此 consume body (会破下游);
        # chunked 守门留待后续 ASGI middleware 重写或 request._receive wrap 增量。
        return await call_next(request)
