"""增量6：RCA 端点（独立分析入口，不走完整 chat 链路）。

POST /api/rca/analyze：建 trace_id，按 problem_type/description 产报告并暂存。
GET /api/rca/{trace_id}：取回该 trace 的 RCA 报告。

已接 mcp_servers/rca.DefaultRCAEngine（确定性 playbook 规则引擎，不执行命令、
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
from backend.app.llm.adapter import LLMAdapter
from mcp_servers.rca import DefaultRCAEngine

router = APIRouter(prefix="/api/rca", tags=["rca"])

# 内存 RCA 报告暂存（trace_id → {"report": dict, "llm_summary": str|None}）。
# TODO: 报告生命周期/持久化待定；本轮内存版让前端能拉取。
_reports: dict[str, dict] = {}

# RCA 引擎（DefaultRCAEngine：无状态确定性规则引擎）。
_rca_engine = DefaultRCAEngine()


async def _produce_llm_summary(
    llm: LLMAdapter | None, evidence: list[dict], report: dict
) -> str | None:
    """之六十八 Task 3: 独立 RCA 端点 LLM 摘要路径.

    调 llm_rewrite_summary 改 report['summary'] 字段 + emit llm_summary 给前端.
    失败/None/凭据命中 → llm_summary 为 None(前端零感知兼容).
    独立端点无 AuditSink,但 routers/chat 路径的 _emit_rca_summary 会落 audit rca_llm_summary;
    本路径用 logger 警告兜底,不重复落审计(审计表零侵入).
    """
    if llm is None:
        return None
    from backend.app.agent.rca_summary_llm import llm_rewrite_summary

    return await llm_rewrite_summary(llm, evidence, report)


def _get_llm_dep() -> LLMAdapter | None:
    """独立 RCA 端点尝试拿全局 llm;lifespan 未启动或 proxy 模式不可用时返 None.

    KYLIN_LLM_FAKE=true → fake stub (返回固定值);否则需 KYLIN_LLM_BASE_URL.
    LLM 不可用时不报错,仅 llm_summary=None 兜底.
    """
    import os

    if os.environ.get("KYLIN_LLM_FAKE", "").strip().lower() == "true":
        from backend.app.api._fakes import build_fake_llm

        return build_fake_llm()
    try:
        from backend.app.api.app import get_llm

        return get_llm()
    except (RuntimeError, AssertionError):
        return None


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

    # 之六十八 Task 2a+3: summary LLM 化 + llm_summary 字段注入
    llm_summary: str | None = None
    if report:
        llm = _get_llm_dep()
        rewritten = await _produce_llm_summary(llm, list(body.evidence or []), report)
        if rewritten:
            report["summary"] = rewritten
            report["summary_source"] = "llm"
            llm_summary = rewritten
        else:
            report.setdefault("summary_source", "playbook")

    _reports[trace_id] = {"report": report, "llm_summary": llm_summary}
    return RCAAnalyzeResponse(trace_id=trace_id, evidence_count=len(body.evidence))


@router.get("/{trace_id}", response_model=RCAReportResponse)
async def get_report(
    trace_id: str,
    _user: str = Depends(verify_token),
) -> RCAReportResponse:
    """取回 RCA 报告；trace_id 未知 → 404.

    之六十八 Task 3: 响应体新增 llm_summary 字段(可选);前端零感知兼容.
    """
    if trace_id not in _reports:
        raise HTTPException(status_code=404, detail=f"unknown rca trace_id: {trace_id}")
    stored = _reports[trace_id]
    return RCAReportResponse(
        trace_id=trace_id,
        report=stored["report"],
        llm_summary=stored.get("llm_summary"),
    )
