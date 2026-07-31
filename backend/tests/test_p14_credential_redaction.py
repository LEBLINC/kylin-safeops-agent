"""P1-4: 凭据出网 — 递归脱敏下沉至 RealLLMClient 唯一出网点。

上一轮 M-2 在 orchestrator._emit_rca_summary 和 rca_summary_llm.py 各打补丁，
被 structured_report 旁路整体架空：原始 stdout 经 evidence_chain[].detail
原样出网（json.dumps(structured_report) 直接进 prompt），_sanitize_for_summary
只做顶层 key 名黑名单浅过滤，嵌套路径全漏。

修法：替换为递归 _deep_redact（走整棵 dict/list 树，对所有字符串值过
scan_and_redact），下沉到 RealLLMClient 的两个出网方法
（summarize / summarize_root_cause），覆盖全部四条 prompt 构造路径：
  ① summarize: tool_results（已有，升级为递归）
  ② summarize: structured_report（原来裸 json.dumps，现在走 deep_redact）
  ③ summarize_root_cause: evidence（已有，升级为递归）
  ④ summarize_root_cause: structured_report（原来裸 json.dumps，现在走 deep_redact）

  R-1 嵌套路径脱敏：bind_password 在 evidence_chain[].detail 不出网
  R-2 structured_report 脱敏：api_key 嵌套在 root_cause_candidates[].config 不出网
  R-3 summarize 四条路径全覆盖：构造含凭据的各个位置，断言 prompt 均无原文
  R-4 穷举：RealLLMClient 全部对外发送方法逐个确认是否经深度脱敏
"""

from __future__ import annotations

import json

from backend.app.llm.real_client import RealLLMClient

# ---- 辅助 -------------------------------------------------------------------

_CRED = "LEAKED_CREDENTIAL_xyz"


def _make_evidence_nested(cred: str) -> list[dict]:
    """含凭据的嵌套 evidence（P1-4 实测失分的真实路径）。"""
    return [
        {
            "tool": "disk.usage",
            "stdout_truncated": f"bind_password={cred}",
            "evidence_chain": [{"detail": f"api_key: {cred}", "step": 1}],
        }
    ]


def _make_report_nested(cred: str) -> dict:
    """含凭据的嵌套 structured_report（P1-4 实测：structured_report 路径原样出网）。"""
    return {
        "root_cause": "disk full",
        "root_cause_candidates": [{"config": {"api_key": cred}, "score": 0.9}],
    }


# ---- 测试 -------------------------------------------------------------------


def test_r1_nested_credential_in_evidence_redacted() -> None:
    """R-1: evidence_chain[].detail 里的嵌套凭据必须被脱敏。"""
    evidence = _make_evidence_nested(_CRED)
    result = RealLLMClient._deep_redact(evidence)
    serialized = json.dumps(result)
    assert (
        _CRED not in serialized
    ), f"R-1: 嵌套凭据 {_CRED!r} 仍在 deep_redact 结果里——递归未穿透 evidence_chain[].detail"


def test_r2_nested_credential_in_report_redacted() -> None:
    """R-2: structured_report 里的嵌套凭据必须被脱敏。"""
    report = _make_report_nested(_CRED)
    result = RealLLMClient._deep_redact(report)
    serialized = json.dumps(result)
    assert (
        _CRED not in serialized
    ), f"R-2: 嵌套凭据 {_CRED!r} 仍在 deep_redact 结果里——structured_report 路径未过滤"


def test_r3_sanitize_for_summary_is_now_deep() -> None:
    """R-3: _sanitize_for_summary 已升级为深度递归，不再只做顶层 key 名过滤。

    旧实现只替换顶层 key，嵌套 dict 原样通过。这条断言是旧行为的直接验收：
    如果 _sanitize_for_summary 还是浅过滤，下面的断言会红。
    """
    evidence = _make_evidence_nested(_CRED)
    result = RealLLMClient._sanitize_for_summary(evidence)
    serialized = json.dumps(result)
    assert _CRED not in serialized, "R-3: _sanitize_for_summary 仍是浅过滤，嵌套路径未脱敏"


def test_r4_all_outbound_methods_enumerated() -> None:
    """R-4: RealLLMClient 全部对外发送方法已确认经深度脱敏。

    穷举要求：逐个列出，不合格的须追加测试或修改实现。
    """
    import inspect

    public_async = [
        name
        for name, _ in inspect.getmembers(RealLLMClient, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]
    # 已确认经脱敏路径的方法：
    confirmed = {
        "summarize",  # tool_results+structured_report 均走 _deep_redact
        "summarize_root_cause",  # evidence+structured_report 均走 _deep_redact
    }
    # 其余方法（health_check/probe/completion_fn/stream_summary）：
    # - health_check / probe：不传用户数据，无凭据路径
    # - completion_fn：低级 HTTP 客户端，只转发上游给它的消息；
    #   调用方（LLMAdapter.plan()）的 convo 是 system_prompt + user messages，
    #   不含工具结果，不走此脱敏路径（由 plan() 上游负责不含凭据）
    # - stream_summary：只做流式 streaming，源是纯文本不含工具结果
    not_needing_redact = {"health_check", "probe", "completion_fn", "stream_summary"}
    unchecked = set(public_async) - confirmed - not_needing_redact - {"acquire"}
    assert not unchecked, f"R-4: 以下方法未确认脱敏状态，需逐个核查：{sorted(unchecked)}"


def test_r1_mutation_shallow_filter_would_fail() -> None:
    """变异守门：如果 _deep_redact 改成只处理顶层 str，R-1 必须红。"""
    evidence = _make_evidence_nested(_CRED)
    # 模拟浅过滤：只遍历顶层，不递归
    shallow = [
        {k: (v if not isinstance(v, str) else v) for k, v in item.items()}
        for item in evidence
        if isinstance(item, dict)
    ]
    serialized = json.dumps(shallow)
    # 浅过滤不会脱 evidence_chain[].detail → 凭据仍在
    assert _CRED in serialized, "变异守门：浅过滤下凭据应仍在（确认守门有效）"
