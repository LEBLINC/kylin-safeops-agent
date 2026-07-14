"""5.1 fake planner 修真守门测试 — adapter.py plan() 真接 LLM (不写死目标)。

覆盖 4 用例:
  T1 plan 解析 user_intent 提 tool + args (不写死 nginx)
  T2 plan 解析 user_intent 提 path 类工具参数
  T3 plan 空 user_intent → 降级 empty intent
  T4 grep adapter.py 静态守门: 0 命中 nginx.service|/var/log/app.log
"""

from __future__ import annotations

import pathlib

# ---- T1: parse_intent unit-level (不依赖 adapter.plan retry loop) ----


def test_t1_planner_parses_intent_extract_tool() -> None:
    """T1: parse_intent() 提取 service_restart + service.restart + service_name='nginx'."""
    from backend.app.llm.adapter import parse_intent

    raw = (
        '{"intent":"service_restart","confidence":0.9,"need_observation":false,'
        '"risk_hint":"high","justification":"user requested nginx restart",'
        '"candidate_tools":[{"name":"service.restart","args":{"service_name":"nginx"}}]}'
    )
    intent = parse_intent(raw)
    assert intent.intent == "service_restart"
    assert len(intent.candidate_tools) >= 1
    assert intent.candidate_tools[0].name == "service.restart"
    assert intent.candidate_tools[0].args["service_name"] == "nginx"


# ---- T2: parse_intent path 类 ----


def test_t2_planner_parses_intent_extract_path() -> None:
    """T2: parse_intent() 提取 path 类工具参数."""
    from backend.app.llm.adapter import parse_intent

    raw = (
        '{"intent":"log_compress_rotate","confidence":0.9,"need_observation":false,'
        '"risk_hint":"medium","justification":"user requested log rotation",'
        '"candidate_tools":[{"name":"log.compress_rotate","args":{"path":"/var/log/app.log"}}]}'
    )
    intent = parse_intent(raw)
    assert intent.candidate_tools[0].name == "log.compress_rotate"
    assert intent.candidate_tools[0].args["path"] == "/var/log/app.log"


# ---- T3: 空 LLM 输出 → adapter.plan 降级 OBSERVE_ONLY_INTENT ----


def test_t3_planner_falls_back_when_parse_fails() -> None:
    """T3: mock _ok 返空字符串 → plan() 3 次 retry 全失败 → 降级 OBSERVE_ONLY_INTENT."""
    import asyncio

    from backend.app.llm.adapter import OBSERVE_ONLY_INTENT, LLMAdapter, LLMConfig

    async def _empty(_m):
        return ""

    cfg = LLMConfig(provider="real")
    adapter = LLMAdapter(cfg, completion_fn=_empty)
    intent = asyncio.run(adapter.plan([{"role": "user", "content": ""}]))
    assert (
        intent.intent == OBSERVE_ONLY_INTENT.intent
    ), f"T3: 期望降级 {OBSERVE_ONLY_INTENT.intent}, got {intent.intent!r}"


# ---- T4: 静态守门 adapter.py 不写死 nginx / log path ----


def test_t4_planner_does_not_write_dead_targets() -> None:
    """T4: grep adapter.py 0 命中 nginx.service|/var/log/app.log (修真守门)."""
    src = pathlib.Path("backend/app/llm/adapter.py").read_text(encoding="utf-8")
    assert "nginx.service" not in src, "T4: adapter.py 不应写死 nginx.service"
    assert "/var/log/app.log" not in src, "T4: adapter.py 不应写死 /var/log/app.log"
