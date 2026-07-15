"""之六十八 Task 2a: report[summary] LLM 化(post-process 钩子).

playbooks.py 的 summary 字段是确定性模板字符串(RCA judgment: ... All evidence
displayed...),智能分析价值有限。本模块提供 ``llm_rewrite_summary``:
- 接收已构建的 structured_report dict(由 X 的 playbooks.build_report 产出)
- 用 LLM 改写 summary 字段(基于 evidence + structured_report)
- 限制:≤200 字 / 不引入未在证据中的事实 / 失败兜底用原 summary
- 独立 RCA 端点 POST/GET 也走同一函数,与 chat 链路保持一致

注:不引入新的 audit phase(L 域不入新审计),复用既有 rca_llm_summary phase
由 _emit_rca_summary 调用点记失败/成功。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.app.agent.secret_scan import scan_and_redact

if TYPE_CHECKING:
    from backend.app.llm.adapter import LLMAdapter


log = logging.getLogger(__name__)

_SUMMARY_MAX_CHARS = 200


async def llm_rewrite_summary(
    llm: LLMAdapter,
    evidence: list[dict],
    structured_report: dict,
) -> str | None:
    """LLM 改写 structured_report['summary'];失败/超长/扫描命中凭据时返回 None.

    真实改写由 llm.summarize 走(已支持 evidence + structured_report kwonly 参数,
    见 llm/adapter.py::summarize 升级)。本函数是 L 域便利封装:
    1) 调 llm.summarize (evidence + structured_report 透传)
    2) 空 / None → 返回 None(调用方保留原 summary,兜底用模板)
    3) >200 字 → 截断 + '...' 后缀
    4) scan_and_redact 扫一遍,命中凭据 → 返回 None(安全兜底,留原 summary)
    5) 返回清理后的文本

    不改 structured_report 入参;调用方拿到返回后自行 report['summary'] = rewritten
    或保留原值(失败兜底)。
    """
    try:
        rewritten = await llm.summarize(
            tool_results=list(evidence),
            user_intent="",
            evidence=list(evidence),
            structured_report=dict(structured_report),
        )
    except Exception as exc:
        log.warning(
            "llm_rewrite_summary: llm.summarize failed (%s); keep playbook summary",
            type(exc).__name__,
        )
        return None

    if not rewritten:
        return None

    text = str(rewritten).strip()
    if not text:
        return None

    # 凭据扫描兜底(决策⑫ 间接注入防御纵深):扫描命中 → 返回 None,保原 summary
    cleaned, hit = scan_and_redact(text)
    if hit:
        log.warning("llm_rewrite_summary: sensitive pattern in LLM summary, drop rewrite")
        return None

    # 长度截断
    if len(cleaned) > _SUMMARY_MAX_CHARS:
        cleaned = cleaned[: _SUMMARY_MAX_CHARS - 3] + "..."

    return cleaned
