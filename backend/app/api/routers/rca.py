"""增量6：RCA 端点（独立分析入口，不走完整 chat 链路）。

POST /api/rca/analyze：建 trace_id，按 problem_type/description 产报告并暂存。
GET /api/rca/{trace_id}：取回该 trace 的 RCA 报告。

已接 X 的 mcp_servers/rca.DefaultRCAEngine（确定性 playbook 规则引擎，不执行命令、
不改系统，只据不可信证据产报告）。独立端点空证据 + 明确 problem_type → 产"采集建议"
型非空报告，前端 RCA 页可对真后端联调。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.deps import verify_token
from backend.app.api.schemas import (
    RCAAnalyzeRequest,
    RCAAnalyzeResponse,
    RCAReportResponse,
)
from mcp_servers.rca import DefaultRCAEngine

router = APIRouter(prefix="/api/rca", tags=["rca"])

# 内存 RCA 报告暂存（trace_id → report dict）。
# TODO: 报告生命周期/持久化待定；本轮内存版让前端能拉取。
_reports: dict[str, dict] = {}

# RCA 引擎（X 的 DefaultRCAEngine：无状态确定性规则引擎）。
_rca_engine = DefaultRCAEngine()


@router.post("/analyze", response_model=RCAAnalyzeResponse)
async def analyze(
    body: RCAAnalyzeRequest,
    _user: str = Depends(verify_token),
) -> RCAAnalyzeResponse:
    """RCA 分析入口（独立于 chat）：按 problem_type/description/evidence 产报告并暂存。

    - evidence 非空 → 真接 DefaultRCAEngine.analyze 走完整 playbook（evidence_count > 0）
    - evidence 空 → 兜底按 problem_type/description 产 "采集建议" 模板壳子
      （evidence_count=0，前端可拿空模板）
    RCA 只产报告，不执行任何工具/命令（红线：本端点不触发执行）。
    """
    trace_id = uuid.uuid4().hex
    # 独立端点：evidence 透传给 RCA 引擎；空列表走 problem_type/description 模板壳子
    report = _rca_engine.analyze_problem(body.problem_type, body.description, body.evidence or None)
    _reports[trace_id] = report
    return RCAAnalyzeResponse(trace_id=trace_id, evidence_count=len(body.evidence))


@router.get("/{trace_id}", response_model=RCAReportResponse)
async def get_report(
    trace_id: str,
    _user: str = Depends(verify_token),
) -> RCAReportResponse:
    """取回 RCA 报告；trace_id 未知 → 404。"""
    if trace_id not in _reports:
        raise HTTPException(status_code=404, detail=f"unknown rca trace_id: {trace_id}")
    return RCAReportResponse(trace_id=trace_id, report=_reports[trace_id])
