"""增量6：RCA 端点（独立分析入口，不走完整 chat 链路）。

POST /api/rca/analyze：建 trace_id，当前用 NullRCA 产空报告并暂存。
GET /api/rca/{trace_id}：取回该 trace 的 RCA 报告。

TODO(BLOCKED-ON-X): RCA playbook（证据采集模板 + 根因推断）归 X 的 mcp_servers/rca/；
本轮仅搭端点 + 调起点 + 桩报告，report 真实结构待 X 定。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from backend.app.agent.rca import NullRCA
from backend.app.api.deps import verify_token
from backend.app.api.schemas import (
    RCAAnalyzeRequest,
    RCAAnalyzeResponse,
    RCAReportResponse,
)

router = APIRouter(prefix="/api/rca", tags=["rca"])

# 内存 RCA 报告暂存（trace_id → report dict）。
# TODO: 报告生命周期/持久化待定；本轮内存版让前端能拉取。
_reports: dict[str, dict] = {}

# 桩 RCA 引擎（待 X 在 mcp_servers/rca/ 实现真编排器替换）
_rca_engine = NullRCA()


@router.post("/analyze", response_model=RCAAnalyzeResponse)
async def analyze(
    body: RCAAnalyzeRequest,
    _user: str = Depends(verify_token),
) -> RCAAnalyzeResponse:
    """RCA 分析入口（独立于 chat）：当前产空报告并暂存，返回 trace_id。

    TODO(BLOCKED-ON-X): 接真实 RCA playbook——按 problem_type 选模板、
    经 gateway 调只读工具采集证据、交 RCAEngine 推断根因。
    """
    trace_id = uuid.uuid4().hex
    # NullRCA 对空证据产空报告；真实现按 problem_type/description 编排
    report = _rca_engine.analyze([])
    _reports[trace_id] = report
    return RCAAnalyzeResponse(trace_id=trace_id)


@router.get("/{trace_id}", response_model=RCAReportResponse)
async def get_report(
    trace_id: str,
    _user: str = Depends(verify_token),
) -> RCAReportResponse:
    """取回 RCA 报告；trace_id 未知 → 404。"""
    if trace_id not in _reports:
        raise HTTPException(status_code=404, detail=f"unknown rca trace_id: {trace_id}")
    return RCAReportResponse(trace_id=trace_id, report=_reports[trace_id])
