"""L 域 /api/audit/* 4 接口（commit 2 增量）。

覆盖：list / detail / verify / export。
认证：require_proxy_identity（决策⑨ mode-aware，proxy fail-closed 401 / dev 放行）。
S9 守卫：list_traces / get_trace_records 已过滤 api_key/authorization/password/
bind_password/secret/token 类敏感字段。
S3 守卫：verify 服务端 recompute（不暴露 hash 算法原文给前端）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from backend.app.agent.ports import AuditSink
from backend.app.api import schemas
from backend.app.api.app import get_audit
from backend.app.api.auth import Principal
from backend.app.api.deps import require_proxy_identity

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/traces", response_model=schemas.AuditTraceListResponse)
async def list_traces(
    limit: int = 50,
    offset: int = 0,
    since: str | None = None,
    until: str | None = None,
    audit: AuditSink = Depends(get_audit),
    _principal: Principal = Depends(require_proxy_identity),
) -> schemas.AuditTraceListResponse:
    """列 trace（按 created_at 倒序，分页 + 时间过滤）。

    limit 上限 500（SqliteAuditSink.list_traces 内部 max）。
    """
    try:
        summaries = audit.list_traces(limit=limit, offset=offset, since=since, until=until)
        total = audit.count_traces(since=since, until=until)
    except AttributeError as exc:
        # 兜底：mock audit 没 list_traces 实现
        raise HTTPException(
            status_code=501, detail=f"audit sink does not support list: {exc}"
        ) from exc
    return schemas.AuditTraceListResponse(
        items=[schemas.AuditTraceSummary(**s) for s in summaries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/traces/{trace_id}", response_model=schemas.AuditTraceDetail)
async def get_trace_detail(
    trace_id: str,
    audit: AuditSink = Depends(get_audit),
    _principal: Principal = Depends(require_proxy_identity),
) -> schemas.AuditTraceDetail:
    """单条 trace 详情（含 records + verify_chain 状态）。

    trace 不存在 → 404（records 空且 verify valid=True 表示空链，区分"无记录"和"不存在"）。
    """
    records = audit.get_trace_records(trace_id)
    if not records:
        # 空链：要么 trace 不存在，要么从未有记录。区分：再 verify 一遍
        result = audit.verify_chain(trace_id)  # type: ignore[attr-defined]
        if result.record_count == 0:  # type: ignore[attr-defined]
            raise HTTPException(status_code=404, detail=f"unknown trace_id: {trace_id}")
    verify = audit.verify_chain(trace_id)  # type: ignore[attr-defined]
    return schemas.AuditTraceDetail(
        trace_id=trace_id,
        records=[schemas.AuditRecord(**r) for r in records],
        verify_chain_valid=verify.valid,  # type: ignore[attr-defined]
        record_count=verify.record_count,  # type: ignore[attr-defined]
        broken_seq=verify.broken_seq,  # type: ignore[attr-defined]
        reason=verify.reason,  # type: ignore[attr-defined]
    )


@router.post("/verify", response_model=schemas.AuditVerifyResponse)
async def verify_chain_endpoint(
    trace_id: str,
    audit: AuditSink = Depends(get_audit),
    _principal: Principal = Depends(require_proxy_identity),
) -> schemas.AuditVerifyResponse:
    """服务端 recompute 整链（不返任何中间 hash 算法给前端）。

    返回 valid + record_count + 第一个错 seq + 原因。
    """
    result = audit.verify_chain(trace_id)  # type: ignore[attr-defined]
    return schemas.AuditVerifyResponse(
        trace_id=trace_id,
        valid=result.valid,  # type: ignore[attr-defined]
        record_count=result.record_count,  # type: ignore[attr-defined]
        broken_seq=result.broken_seq,  # type: ignore[attr-defined]
        reason=result.reason,  # type: ignore[attr-defined]
    )


@router.get("/traces/{trace_id}/export")
async def export_trace(
    trace_id: str,
    audit: AuditSink = Depends(get_audit),
    _principal: Principal = Depends(require_proxy_identity),
) -> Response:
    """导出单条 trace 为 jsonl（每行一条 record，S9 敏感字段已过滤）。

    trace 不存在 → 404。
    """
    records = audit.get_trace_records(trace_id)
    if not records:
        verify = audit.verify_chain(trace_id)  # type: ignore[attr-defined]
        if verify.record_count == 0:  # type: ignore[attr-defined]
            raise HTTPException(status_code=404, detail=f"unknown trace_id: {trace_id}")
    verify = audit.verify_chain(trace_id)  # type: ignore[attr-defined]
    lines: list[str] = []
    for r in records:
        lines.append(json.dumps(r, ensure_ascii=False))
    # 末尾加一行 verify_chain 状态（jsonl 解析友好）
    lines.append(
        json.dumps(
            {
                "_meta": "verify_chain",
                "trace_id": trace_id,
                "valid": verify.valid,  # type: ignore[attr-defined]
                "record_count": verify.record_count,  # type: ignore[attr-defined]
                "broken_seq": verify.broken_seq,  # type: ignore[attr-defined]
                "reason": verify.reason,  # type: ignore[attr-defined]
            },
            ensure_ascii=False,
        )
    )
    body = "\n".join(lines) + "\n"
    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{trace_id}.jsonl"',
        },
    )
