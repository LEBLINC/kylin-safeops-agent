"""之七十五 M-10（原 RCA Task 2b）：root_cause LLM 化 + 失败回退硬编码。

playbooks.py 的 root_cause 取自 root_cause_candidates[0].cause，是确定性硬编码
字符串——对固定场景准确，但不贴合实际证据数值。M-10 让它可选 LLM 化，沿用
llm_rewrite_summary 的同一套 fallback 范式。

关键设计：返回 None 是**合法正常路径**而非错误——确定性 playbook 结论永远可用，
LLM 只是可选增强。故 LLM 不可用绝不能让 RCA 链路崩或降级（S8 在 RCA 侧的延续）。

  M10-1 LLM 返回文本 → root_cause 被改写 + root_cause_source=llm
  M10-2 LLM 返 None（拒答）→ 保留 playbook 原文案 + source=playbook
  M10-3 LLM 抛异常（超时/网络）→ 同样回退，且**不抛出**（链路不崩）
  M10-4 LLM 输出命中凭据 → 丢弃改写（安全兜底优先），保留原文案
  M10-5 超长输出截断到 120 字（root_cause 是一句结论）
  M10-6 不改入参 report（副本语义）
  M10-7 summary 与 root_cause 各自独立判定——一个成功一个失败是正常组合
"""

from __future__ import annotations

import asyncio
from unittest import mock

from backend.app.agent.rca_summary_llm import llm_rewrite_root_cause
from backend.app.llm.adapter import LLMAdapter

_PLAYBOOK_CAUSE = "Disk usage exceeded threshold on /dev/sda1"


def _llm(return_value=None, side_effect=None):
    """带 summarize_root_cause 能力的 adapter（spec=LLMAdapter 已含该方法）。"""
    adapter = mock.MagicMock(spec=LLMAdapter)
    adapter.summarize = mock.AsyncMock(return_value="不该被用到")
    adapter.summarize_root_cause = mock.AsyncMock(
        return_value=return_value, side_effect=side_effect
    )
    return adapter


def _llm_without_capability():
    """不具备 root_cause 改写能力的 adapter（fake/fixture 路径的形态）。"""
    adapter = mock.MagicMock(spec=["summarize"])
    adapter.summarize = mock.AsyncMock(return_value="已完成:disk.usage")
    return adapter


def _report() -> dict:
    return {
        "problem_type": "disk_full",
        "root_cause": _PLAYBOOK_CAUSE,
        "root_cause_candidates": [{"cause": _PLAYBOOK_CAUSE, "confidence": 0.8}],
        "summary": "playbook summary",
    }


_EVIDENCE = [{"tool": "disk.usage", "stdout_truncated": "/dev/sda1 96% /", "exit_code": 0}]


def test_m10_1_llm_text_rewrites_root_cause() -> None:
    """M10-1: LLM 返回文本 → 采用为 root_cause。"""
    llm = _llm("根分区 /dev/sda1 使用率 96%，由 /var/log 下日志堆积导致")
    result = asyncio.run(llm_rewrite_root_cause(llm, _EVIDENCE, _report()))
    assert result is not None
    assert "96%" in result


def test_m10_2_llm_none_falls_back() -> None:
    """M10-2: LLM 拒答（返 None）→ 返回 None，调用方保留 playbook 原文案。"""
    assert asyncio.run(llm_rewrite_root_cause(_llm(None), _EVIDENCE, _report())) is None
    assert asyncio.run(llm_rewrite_root_cause(_llm(""), _EVIDENCE, _report())) is None
    assert asyncio.run(llm_rewrite_root_cause(_llm("   "), _EVIDENCE, _report())) is None


def test_m10_3_llm_exception_does_not_propagate() -> None:
    """M10-3: LLM 抛异常 → 回退 None 且不抛（RCA 链路不得因 LLM 不可用而崩）。"""
    import httpx

    for exc in (httpx.ConnectError("no route"), TimeoutError("timeout"), RuntimeError("boom")):
        result = asyncio.run(llm_rewrite_root_cause(_llm(side_effect=exc), _EVIDENCE, _report()))
        assert result is None, f"M10-3: {type(exc).__name__} 应回退 None"


def test_m10_4_credential_hit_drops_rewrite() -> None:
    """M10-4: LLM 输出含凭据 → 整条丢弃（安全兜底优先于可读性）。"""
    llm = _llm("根因：连接串 password=hunter2-super-secret 失效")
    assert asyncio.run(llm_rewrite_root_cause(llm, _EVIDENCE, _report())) is None


def test_m10_5_overlong_output_truncated() -> None:
    """M10-5: 超长输出截断到 120 字并带 ... 后缀。"""
    result = asyncio.run(llm_rewrite_root_cause(_llm("根因" * 200), _EVIDENCE, _report()))
    assert result is not None
    assert len(result) == 120
    assert result.endswith("...")


def test_m10_6_input_report_not_mutated() -> None:
    """M10-6: 不改入参 report（调用方自行赋值，副本语义与 summary 版一致）。"""
    report = _report()
    asyncio.run(llm_rewrite_root_cause(_llm("新根因"), _EVIDENCE, report))
    assert report["root_cause"] == _PLAYBOOK_CAUSE, "M10-6: 不应就地改写入参"


def test_m10_7_orchestrator_marks_sources_independently() -> None:
    """M10-7: orchestrator 里 summary 与 root_cause 各自独立标记来源。

    一个成功一个失败是正常组合（两次独立 LLM 调用），故不共用 source 标记。
    这里验源码层：两个 *_source 字段都存在且分别赋值。
    """
    import inspect

    from backend.app.agent import orchestrator as orch_mod

    src = inspect.getsource(orch_mod._execute_batch) if hasattr(orch_mod, "_execute_batch") else ""
    if not src:
        src = inspect.getsource(orch_mod.Orchestrator._execute_batch)
    assert 'report["summary_source"] = "llm"' in src
    assert 'report["root_cause_source"] = "llm"' in src
    assert 'report["root_cause_source"] = "playbook"' in src


def test_m10_8_no_capability_falls_back_not_hijack_summary() -> None:
    """M10-8: 适配器无 root_cause 能力 → 回退 None，**绝不**借用通用摘要通道。

    这是 M-10 初版的真实缺陷：曾复用 llm.summarize 并把意图塞进 structured_report，
    但 default/fake/fixture 的 summary_fn 完全忽略该字段，返回的是通用摘要
    （"已完成:disk.usage"）——写进 root_cause 就等于用摘要覆盖了正确的 playbook
    规则结论，比不改写更糟。test_rca.py 当场抓到。本用例锁死修复后的行为。
    """
    llm = _llm_without_capability()
    result = asyncio.run(llm_rewrite_root_cause(llm, _EVIDENCE, _report()))

    assert result is None, "M10-8: 无能力时必须回退，不得改写"
    llm.summarize.assert_not_awaited()  # 关键：不得借用摘要通道
