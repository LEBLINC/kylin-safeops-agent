"""L-H16 TraceIdMiddleware - 每请求注入 trace_id contextvar (纯中间件)。"""

from __future__ import annotations

import os
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

_DEFAULT_MAX_BYTES = 1024 * 1024  # 1MB


def _max_request_bytes() -> int:
    """读 KYLIN_MAX_REQUEST_BYTES env;默认 1MB。"""
    raw = os.environ.get("KYLIN_MAX_REQUEST_BYTES", "")
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


# ============================================================
# B5 P3 (B6 follow-up): ASGI-level chunked body 守门 (L-M5 chunked path)
# ============================================================


class ASGIMaxBodySizeMiddleware:
    """ASGI-level 守门:Content-Length + chunked 累计 body 字节。

    B5 commit 2 L-M5 (RequestSizeLimitMiddleware) 仅 Content-Length 路径;
    chunked transfer 可绕过 (生产风险)。本 P3 增量补 ASGI 路径,wrap receive
    callable 累计累计字节超限即短响应 413 终止流。

    B5 report 留底: 不走 request._receive (Starlette 私有, 升级脆弱);
    走 ASGI 原生 receive callable (官方稳定接口)。
    """

    def __init__(self, app, max_bytes: int | None = None) -> None:
        self.app = app
        self.max_bytes = max_bytes if max_bytes is not None else _max_request_bytes()

    async def __call__(self, scope, receive, send):
        """ASGI 入口:Content-Length 路径直接判定;chunked path wrap receive 累计.

        chunked 路径**流式** 转发 (不 buffer 整个 body),保持 SSE streaming 不阻塞.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Content-Length header path (deterministic)
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    cl = int(value.decode("latin-1"))
                except (ValueError, UnicodeDecodeError):
                    cl = -1
                if cl > self.max_bytes:
                    await _send_413(send)
                    return
                break

        # chunked path: 流式 wrap receive (增量累计, 超限立即 413 + 终止流)
        received_bytes = 0

        async def _gated_receive():
            nonlocal received_bytes
            message = await receive()
            msg_type = message.get("type")
            if msg_type == "http.request":
                body = message.get("body", b"") or b""
                received_bytes += len(body)
                if received_bytes > self.max_bytes:
                    raise _ChunkedTooLarge()
            return message

        try:
            await self.app(scope, _gated_receive, send)
        except _ChunkedTooLarge:
            await _send_413(send)
            return


class _ChunkedTooLarge(Exception):
    """chunked 超限 sentinel — 不污染 ASGI 错误流。"""


async def _send_413(send) -> None:
    """ASGI 直发 413 JSONResponse (不调 Starlette 响应对象,避免循环依赖)."""
    import json as _json

    payload = _json.dumps({"detail": "request_too_large"}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})
