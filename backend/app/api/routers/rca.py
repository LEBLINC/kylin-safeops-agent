"""增量6：RCA 端点（独立分析入口，不走完整 chat 链路）。

POST /api/rca/analyze：建 trace_id，按场景模板跑只读采证 + 产报告并暂存。
GET /api/rca/{trace_id}：取回该 trace 的 RCA 报告。

已接 mcp_servers/rca.DefaultRCAEngine（确定性 playbook 规则引擎，不执行命令、
不改系统，只据不可信证据产报告）。

G-2 红线改写（架构者 2026-07-31 裁定 B + 两条件）：本端点原 docstring 写
"RCA 只产报告，不执行任何工具/命令"。该句的前半段今天已经是假的——主链路
orchestrator.py:589 早已调 collect_rca_evidence 真跑只读工具并落审计；
只有本端点还声称自己不跑，于是独立 RCA 页的 evidence_chain 永远只有
"用户自己输入的那一条"，EvidenceTree.vue / HashChainViewer.vue 与五套场景
模板全是死代码。现改为与主链路同源采证，并同时补上审计——**只读与留痕
两个条件绑定，缺一不采**（见 analyze 的红线段与 _append_evidence_audit）。
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from backend.app.agent.rca_drive import collect_rca_evidence
from backend.app.api.deps import verify_token
from backend.app.api.schemas import (
    RCAAnalyzeRequest,
    RCAAnalyzeResponse,
    RCAReportResponse,
)
from backend.app.contracts.audit import GENESIS_HASH, AuditRecord, compute_curr_hash
from backend.app.contracts.untrusted import ToolResult
from backend.app.llm.adapter import LLMAdapter
from mcp_servers.rca import DefaultRCAEngine

if TYPE_CHECKING:
    from backend.app.agent.ports import AuditSink
    from backend.app.mcp.gateway import MCPGateway

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rca", tags=["rca"])

#: 整轮采证的时间上界（秒）。本端点是 HTTP 同步请求，真机上 find 无 -xdev/-size
#: 约束时单步可达 30s（P2-7 已登记），没有上界会把一次 RCA 查询挂死。
#: 超时按已采到的部分出报告（见 collect_rca_evidence 的 budget_s）。
_EVIDENCE_BUDGET_S = 8.0

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
    from backend.app.agent.rca_summary_llm import (
        llm_rewrite_root_cause,
        llm_rewrite_summary,
    )

    # 之七十五 M-10：root_cause 也 LLM 化（与 chat 主链路同口径），失败回退 playbook。
    # in-place 改 report 后由调用方一并返回给前端；两字段各自独立判定来源。
    rewritten_cause = await llm_rewrite_root_cause(llm, evidence, report)
    if rewritten_cause:
        report["root_cause"] = rewritten_cause
        report["root_cause_source"] = "llm"
    else:
        report["root_cause_source"] = "playbook"

    return await llm_rewrite_summary(llm, evidence, report)


def optional_gateway() -> MCPGateway | None:
    """取全局 MCPGateway；lifespan 未启动 → None（不 500）。

    做成 Depends provider 而非内联调用，是为了让测试能用 dependency_overrides
    注入确定性 gateway：真 executor 在 Windows 上 df/find 跑不起来、在 Linux 上
    跑得起来，行为依赖平台的断言正是 Z-9 钉住的那一类坑。
    """
    try:
        from backend.app.api.app import get_gateway

        return get_gateway()
    except (RuntimeError, AssertionError):
        return None


def optional_audit() -> AuditSink | None:
    """取全局 AuditSink；lifespan 未启动 → None（不 500）。理由同 optional_gateway。"""
    try:
        from backend.app.api.app import get_audit

        return get_audit()
    except (RuntimeError, AssertionError):
        return None


def _append_evidence_audit(audit: AuditSink, trace_id: str, collected: list[ToolResult]) -> None:
    """把本次采证写进哈希链，payload 与主链路同构。

    形状照 orchestrator.py 的 {"rca_scenario_evidence": [tool, ...]}——两条 RCA
    路径的审计记录可比对，不产生"同一件事两种记法"。

    seq=0 / prev=GENESIS_HASH：本端点每次调用都新建 trace_id（见 analyze），
    这条链自 0 起，不存在续接问题。（approvals.py 的 escalate 是往**已有**链上
    追加却也写死 seq=0，那是另一处隐患，不在本次范围。）

    **不吞异常**：audit.append 失败即 500，照 approvals.py 的 B6 L-M1 定论
    （S8 fail-closed 不吞）。留痕是本端点获准执行只读工具的前提条件，
    写不进链就该让调用方知道，而不是静默变成"真执行零审计"。
    """
    payload: dict = {"rca_scenario_evidence": [e.tool for e in collected]}
    audit.append(
        AuditRecord(
            trace_id=trace_id,
            seq=0,
            phase="rca_scenario_evidence",
            payload=payload,
            prev_hash=GENESIS_HASH,
            curr_hash=compute_curr_hash(GENESIS_HASH, payload),
        )
    )


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
    gateway: MCPGateway | None = Depends(optional_gateway),
    audit: AuditSink | None = Depends(optional_audit),
) -> RCAAnalyzeResponse:
    """RCA 分析入口（独立于 chat）：按场景模板只读采证 + 产报告并暂存。

    - 请求体 evidence 非空 → 一并喂给 DefaultRCAEngine.analyze 走完整 playbook
    - 请求体 evidence 空 → 仅用采证结果 + problem_type/description
    - 采证与请求体 evidence 均空 → 兜底产 "采集建议" 模板壳子（evidence_count=0）

    **红线（G-2 改写，2026-07-31 架构者裁定）**：本端点不执行任何变更类工具；
    仅经 gateway 跑 R0/R1 只读采证，且每次采证必写审计记录。
    只读性由 gateway.is_read_only 闸强制、留痕由哈希链强制，**都不靠本注释保证**：
    - 只读闸在 collect_rca_evidence 内（非只读 → 跳过，不执行）；
    - 留痕见 _append_evidence_audit（写不进链就 500，不静默放过）；
    - 守门用例遍历实际调用断言"执行过的工具集合 ⊆ 只读工具集合"，
      日后谁往场景模板里塞一个变更工具，当次红。

    gateway/audit 任一不可用（lifespan 未启动）→ **不采证**，退回纯报告行为。
    两个条件绑定是刻意的：能执行但记不下来，正是这条红线当初要拦的东西。
    """
    trace_id = uuid.uuid4().hex
    # 请求体 evidence（前端已观测/已执行的结果）与本端点采证结果同列喂引擎。
    # 引擎侧 _collect_evidence_items 用 _read_attr 兼容 dict 与 ToolResult 两种形态。
    evidence: list[dict[str, object] | ToolResult] = list(body.evidence or [])

    if gateway is not None and audit is not None:
        collected = await collect_rca_evidence(
            gateway,
            _rca_engine,
            body.description,
            problem_type=body.problem_type,
            budget_s=_EVIDENCE_BUDGET_S,
        )
        if collected:
            evidence.extend(collected)
            _append_evidence_audit(audit, trace_id, collected)
    else:
        logger.debug("RCA 端点：gateway/audit 不可用（lifespan 未启动），跳过场景采证")

    report = _rca_engine.analyze_problem(body.problem_type, body.description, evidence or None)

    # 之六十八 Task 2a+3: summary LLM 化 + llm_summary 字段注入
    llm_summary: str | None = None
    if report:
        llm = _get_llm_dep()
        # LLM 侧契约是 list[dict]（_redact_evidence 会 dict(item)）；采证结果是
        # ToolResult，显式 model_dump 转一次，不依赖 pydantic 的 dict(model) 隐式行为。
        llm_evidence = [e if isinstance(e, dict) else e.model_dump() for e in evidence]
        rewritten = await _produce_llm_summary(llm, llm_evidence, report)
        if rewritten:
            report["summary"] = rewritten
            report["summary_source"] = "llm"
            llm_summary = rewritten
        else:
            report.setdefault("summary_source", "playbook")

    _reports[trace_id] = {"report": report, "llm_summary": llm_summary}
    # evidence_count = 真正喂给引擎的条数（请求体 evidence + 本端点采证），
    # 不再只数请求体——否则采到 4 条证据、响应仍报 0，与 evidence_chain 自相矛盾。
    return RCAAnalyzeResponse(trace_id=trace_id, evidence_count=len(evidence))


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
