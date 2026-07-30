"""之六十八 Task 2a: report[summary] LLM 化(post-process 钩子).

playbooks.py 的 summary 字段是确定性模板字符串(RCA judgment: ... All evidence
displayed...),智能分析价值有限。本模块提供 ``llm_rewrite_summary``:
- 接收已构建的 structured_report dict(由 RCA 引擎 playbooks.build_report 产出)
- 用 LLM 改写 summary 字段(基于 evidence + structured_report)
- 限制:≤200 字 / 不引入未在证据中的事实 / 失败兜底用原 summary
- 独立 RCA 端点 POST/GET 也走同一函数,与 chat 链路保持一致

注:不引入新的 audit phase(不入新审计),复用既有 rca_llm_summary phase
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


def _redact_evidence(evidence: list[dict]) -> list[dict]:
    """S9 输入侧脱敏（之七十五 M-2）：扫 evidence 里承载命令输出的自由文本字段。

    只扫 stdout_truncated / stdout：结构化字段（tool/args/exit_code）是受控值，
    扫它们只有误伤没有收益。不改入参（返回浅拷贝后的新 dict）。
    """
    safe: list[dict] = []
    for item in evidence:
        row = dict(item)
        for key in ("stdout_truncated", "stdout"):
            value = row.get(key)
            if isinstance(value, str) and value:
                row[key], _ = scan_and_redact(value)
        safe.append(row)
    return safe


async def llm_rewrite_summary(
    llm: LLMAdapter,
    evidence: list[dict],
    structured_report: dict,
) -> str | None:
    """LLM 改写 structured_report['summary'];失败/超长/扫描命中凭据时返回 None.

    真实改写由 llm.summarize 走(已支持 evidence + structured_report kwonly 参数,
    见 llm/adapter.py::summarize 升级)。本函数是编排层便利封装:
    1) 调 llm.summarize (evidence + structured_report 透传)
    2) 空 / None → 返回 None(调用方保留原 summary,兜底用模板)
    3) >200 字 → 截断 + '...' 后缀
    4) scan_and_redact 扫一遍,命中凭据 → 返回 None(安全兜底,留原 summary)
    5) 返回清理后的文本

    不改 structured_report 入参;调用方拿到返回后自行 report['summary'] = rewritten
    或保留原值(失败兜底)。

    之七十五 M-2: evidence 送出前先过 S9 脱敏（与 orchestrator._emit_natural_language
    同口径）。此前只在输出侧扫,凭据会原样出网到 LLM 网关,输出侧再 redact 也追不回。
    """
    safe_evidence = _redact_evidence(evidence)
    try:
        rewritten = await llm.summarize(
            tool_results=safe_evidence,
            user_intent="",
            evidence=safe_evidence,
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


#: root_cause 单条判断的长度上限（比 summary 更短：它是一句结论，不是段落）。
_ROOT_CAUSE_MAX_CHARS = 120


async def llm_rewrite_root_cause(
    llm: LLMAdapter,
    evidence: list[dict],
    structured_report: dict,
) -> str | None:
    """LLM 改写 structured_report['root_cause']；不支持/异常/拒答/命中凭据 → None。

    之七十五 M-10（原 RCA Task 2b）。playbooks.py 的 root_cause 来自
    root_cause_candidates[0].cause，是确定性硬编码字符串——对固定场景准确但不贴合
    实际证据数值。本函数沿用 llm_rewrite_summary 的 fallback 范式：任何不确定
    都返回 None，让调用方保留 playbook 原文案。

    **为什么需要专用能力探测（踩坑记录）**：初版复用 llm.summarize 通道、把
    "要改写 root_cause"的意图塞进 structured_report 的一个提示字段。但
    default/fake/fixture 的 summary_fn **完全忽略** structured_report
    （见 adapter.py::summarize 注释），于是提示被静默丢弃，返回的是通用摘要
    （fake 实现恒返 "已完成:<tools>"）——把它写进 root_cause 等于用摘要覆盖了
    正确的 playbook 结论，比不改写更糟。test_rca.py 立刻抓到了这一点。
    改为显式探测 llm.summarize_root_cause：只有适配器真正提供该能力时才改写，
    否则一律回退。这样 fake/fixture 路径行为零变化。

    1) 适配器无 summarize_root_cause → None（回退，不借用通用摘要通道）
    2) 空 / None / 异常 → None
    3) scan_and_redact 命中凭据 → None（安全兜底优先于可读性）
    4) >120 字 → 截断 + '...'（root_cause 是一句结论，不是段落）

    **返回 None 是完全合法的正常路径**：确定性 playbook 结论永远可用，LLM 只是
    可选增强，绝不因 LLM 不可用而让 RCA 链路崩或降级（S8 在 RCA 侧的延续）。
    不改 structured_report 入参；调用方拿到返回后自行赋值或保留原值。
    """
    rewrite = getattr(llm, "summarize_root_cause", None)
    if rewrite is None or not callable(rewrite):
        log.debug("llm_rewrite_root_cause: adapter 无 summarize_root_cause 能力，保留 playbook")
        return None

    safe_evidence = _redact_evidence(evidence)
    try:
        rewritten = await rewrite(
            evidence=safe_evidence,
            structured_report=dict(structured_report),
        )
    except Exception as exc:
        log.warning(
            "llm_rewrite_root_cause: 调用失败 (%s); keep playbook root_cause",
            type(exc).__name__,
        )
        return None

    if not rewritten:
        return None
    text = str(rewritten).strip()
    if not text:
        return None

    cleaned, hit = scan_and_redact(text)
    if hit:
        log.warning("llm_rewrite_root_cause: sensitive pattern in LLM output, drop rewrite")
        return None

    if len(cleaned) > _ROOT_CAUSE_MAX_CHARS:
        cleaned = cleaned[: _ROOT_CAUSE_MAX_CHARS - 3] + "..."
    return cleaned
