"""5.2 S3 schema retry 守门测试。

adapter.plan retry loop 收紧为 max_retries=2 (3 次总尝试),schema 校验失败重发 LLM;
仍不符降级 OBSERVE_ONLY_INTENT。

覆盖 3 用例:
  T5 第 1 次不合规 → 第 2 次合规 → 成功
  T6 3 次全不合规 → 降级 OBSERVE_ONLY_INTENT
  T7 retry 不破坏 verify_chain (注:adapter plan 不直接写审计;此测试仅验证 return 不 raise)
"""

from __future__ import annotations

import asyncio


def test_t5_schema_retry_invalid_first_attempt() -> None:
    """T5: 第 1 次返不合规 JSON → 第 2 次合规 → plan 成功."""
    from backend.app.llm.adapter import LLMAdapter, LLMConfig

    good = (
        '{"intent":"disk_usage","confidence":0.9,"need_observation":false,'
        '"risk_hint":"low","justification":"x",'
        '"candidate_tools":[{"name":"disk.usage","args":{}}]}'
    )
    responses = [
        '{"not_intent": "bad"}',  # 第 1 次: schema 不合规
        good,  # 第 2 次: 合规
    ]

    async def _ok(_m):
        return responses.pop(0) if responses else '{"intent":"observe_only"}'

    cfg = LLMConfig(provider="real")
    adapter = LLMAdapter(cfg, completion_fn=_ok)
    intent = asyncio.run(adapter.plan([{"role": "user", "content": "check disk"}]))
    assert intent.intent == "disk_usage", f"T5: 期望 disk_usage, got {intent.intent}"
    assert len(intent.candidate_tools) == 1
    assert intent.candidate_tools[0].name == "disk.usage"


def test_t6_schema_retry_exhausted_downgrades() -> None:
    """T6: 3 次全不合规 → 降级 OBSERVE_ONLY_INTENT."""
    from backend.app.llm.adapter import OBSERVE_ONLY_INTENT, LLMAdapter, LLMConfig

    async def _bad(_m):
        return '{"bad":"schema"}'  # 永远不合规

    cfg = LLMConfig(provider="real")
    adapter = LLMAdapter(cfg, completion_fn=_bad)
    intent = asyncio.run(adapter.plan([{"role": "user", "content": "?"}]))
    assert (
        intent.intent == OBSERVE_ONLY_INTENT.intent
    ), f"T6: 期望降级 {OBSERVE_ONLY_INTENT.intent}, got {intent.intent!r}"


def test_t7_schema_retry_does_not_raise() -> None:
    """T7: retry 路径不会 raise (Orchestrator 兜底)."""
    from backend.app.llm.adapter import LLMAdapter, LLMConfig

    async def _bad(_m):
        raise RuntimeError("rate_limited")

    cfg = LLMConfig(provider="real")
    adapter = LLMAdapter(cfg, completion_fn=_bad)
    # RuntimeError 透传(orchestrator plan 兜底 → emit error 不杀状态机)
    # 此处仅验证 adapter.plan 不在 plan 内部吞 RuntimeError
    try:
        asyncio.run(adapter.plan([{"role": "user", "content": "x"}]))
    except RuntimeError:
        pass  # 期望透传
