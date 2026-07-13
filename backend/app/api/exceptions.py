"""L-M6: HTTPException detail 固定文案 (防信息泄露)。

全量端点 HTTPException 抛错时,response detail 强制走 SAFE_DETAIL 映射;
原文 detail 仅 logger.exception 记 audit/log 不返客户端。

S9: 密钥/路径等敏感字段在 upstream 层已 S9 黑名单过滤;本守门只防
HTTPException(detail="...") 把内部 traceback/SQL/路径泄漏出去。
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


SAFE_DETAIL: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "request_too_large",
    415: "unsupported_media_type",
    422: "unprocessable_entity",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
    504: "gateway_timeout",
}


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """全量 HTTPException 守门:返 SAFE_DETAIL,原文 detail 仅 logger.exception。

    S9/S8 守门:原文 detail 可能含路径/堆栈/SQL片段,绝不入响应体;logger 仅
    服务端 log + audit(无明文凭据外流)。
    """
    safe_detail = SAFE_DETAIL.get(exc.status_code, "internal_error")
    logger.exception(
        "HTTP exception: status=%s safe_detail=%s origin_detail=%s path=%s",
        exc.status_code,
        safe_detail,
        exc.detail,
        request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": safe_detail},
    )


__all__ = ["SAFE_DETAIL", "http_exception_handler"]
