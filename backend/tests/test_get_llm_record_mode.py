"""get_llm() KYLIN_LLM_RECORD 录制模式分支守门（ADR-0005 demo-record-mode）。

3 用例锁 4 种 env 组合：
- T1 默认（env unset）       → fake 桩 completion_fn（保留 ADR-0003 demo-only）
- T2 KYLIN_LLM_RECORD=true   → RealLLMClient.completion_fn（ADR-0005 录制模式）
- T3 KYLIN_LLM_RECORD=false  → fake 桩 completion_fn（明确"未启用"语义）

不破坏 ADR-0003 默认 fixture 强钉（§5 红线另由 test_d2_chat_always_fixture.py
守门）。仅录视频场景使用；生产 KYLIN_LLM_RECORD 永远 false。

实现说明：build_fake_llm 返 ``LLMAdapter(completion_fn=<local fake>)``，
直接用 ``isinstance(llm, RealLLMClient)`` 不区分得清（不在继承树）。改用
``completion_fn 隶属对象类型`` 区判：fake 桩是 local closure，
RealLLMClient 模式 ``__self__`` 是 RealLLMClient 实例。
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.app.api.app import create_app, get_llm, lifespan


def _completion_fn_origin(llm: Any) -> str:
    """返 completion_fn 的来源描述：fake 桩 = 'fake_closure'，
    RealLLMClient.completion_fn = 'RealLLMClient'。"""
    # 录制模式直接返 RealLLMClient 实例；默认 fake 返 LLMAdapter
    cls_name = type(llm).__name__
    if cls_name == "RealLLMClient":
        return "RealLLMClient"
    fn = getattr(llm, "_completion_fn", None)
    if fn is not None:
        self_obj = getattr(fn, "__self__", None)
        if self_obj is not None and type(self_obj).__name__ == "RealLLMClient":
            return "RealLLMClient"
        qualname = getattr(fn, "__qualname__", "")
        if "RealLLMClient" in qualname:
            return "RealLLMClient"
    return "fake_closure"


def _resolved_via_lifespan() -> str:
    """同步驱动：lifespan 启动后调 get_llm()，返 completion_fn 来源描述。"""

    async def _run() -> str:
        async with lifespan(create_app()):
            llm = get_llm()
            return _completion_fn_origin(llm)

    return asyncio.run(_run())


# ---- T1: 默认（env unset）→ fake fixture ---------------------------------


def test_get_llm_default_returns_real(monkeypatch) -> None:
    """get_llm() 默认行为 (ADR-0006 real-mode-by-default) → 真接 LLM.

    KYLIN_LLM_FAKE=true 显式 opt-in 可回 fake 桩 (演示 / 单测场景).
    """
    monkeypatch.delenv("KYLIN_LLM_RECORD", raising=False)
    monkeypatch.delenv("KYLIN_LLM_FAKE", raising=False)

    # ADR-0006: 默认走真接; KYLIN_LLM_BASE_URL 必须设 (否则 base_url 是 placeholder)
    monkeypatch.setenv("KYLIN_LLM_BASE_URL", "http://mock-llm/v1")
    monkeypatch.setenv("KYLIN_LLM_API_KEY", "test-key-for-real-mode")

    origin = _resolved_via_lifespan()
    assert origin == "RealLLMClient", (
        f"ADR-0006 violation: default get_llm() completion_fn origin = {origin!r}, "
        "expected 'RealLLMClient' (real-mode-by-default)"
    )


def test_get_llm_fake_opt_in_returns_fake(monkeypatch) -> None:
    """get_llm() KYLIN_LLM_FAKE=true 显式 opt-in → fake 桩 (兼容 ADR-0003 demo 场景).

    X P5 fix 增强: 同时 verify summary_fn 是 fake closure (非 real.summarize).
    """
    monkeypatch.setenv("KYLIN_LLM_FAKE", "true")

    async def _drive():
        async with lifespan(create_app()):
            llm = get_llm()
            assert _completion_fn_origin(llm) == "fake_closure"
            # 增强: verify summary_fn != RealLLMClient.summarize
            from backend.app.llm.real_client import RealLLMClient

            assert (
                llm._summary_fn != RealLLMClient.summarize
            ), "X P5 fix violation: KYLIN_LLM_FAKE=true 应走 fake summary_fn (非 real.summarize)"
            return llm

    _drive()
    origin = _resolved_via_lifespan()
    assert origin == "fake_closure", f"KYLIN_LLM_FAKE=true 应返 fake_closure, got {origin!r}"


# ---- T3: 默认 real 模式 → summary_fn == real.summarize ------------------


def test_t3_default_real_mode_summary_fn_is_real(monkeypatch) -> None:
    """X P5 fix: 默认 real 模式下, llm._summary_fn == RealLLMClient.summarize (修真真接)."""
    monkeypatch.delenv("KYLIN_LLM_RECORD", raising=False)
    monkeypatch.delenv("KYLIN_LLM_FAKE", raising=False)
    monkeypatch.setenv("KYLIN_LLM_BASE_URL", "http://mock-llm/v1")
    monkeypatch.setenv("KYLIN_LLM_API_KEY", "test-key-for-real-mode")

    async def _drive():
        async with lifespan(create_app()):
            llm = get_llm()
            from backend.app.llm.real_client import RealLLMClient

            assert (
                llm._summary_fn.__func__ is RealLLMClient.summarize
            ), f"X P5 fix: default summary_fn = RealLLMClient.summarize; got {llm._summary_fn!r}"

    asyncio.run(_drive())


# ---- T2: KYLIN_LLM_RECORD=true → RealLLMClient ----------------------------


def test_get_llm_record_mode_returns_real(monkeypatch) -> None:
    """get_llm() 在 KYLIN_LLM_RECORD=true → 走 RealLLMClient（录制模式）。

    守门 ADR-0005 demo-record-mode：录制场景可切真 LLM。仍受 D2 §5 红线
    守门约束（仅显式 opt-in 启用；默认/生产 KYLIN_LLM_RECORD=false）。
    """
    monkeypatch.setenv("KYLIN_LLM_RECORD", "true")

    origin = _resolved_via_lifespan()
    assert origin == "RealLLMClient", (
        f"ADR-0005 violation: KYLIN_LLM_RECORD=true get_llm() completion_fn "
        f"origin = {origin!r}, expected 'RealLLMClient'"
    )


# ---- T3: KYLIN_LLM_RECORD=false → fake fixture ----------------------------


def test_get_llm_record_off_returns_fake(monkeypatch) -> None:
    """get_llm() 在 KYLIN_LLM_RECORD=false → KYLIN_LLM_FAKE=true 显式 opt-in → 走 fake 桩.

    ADR-0006: 显式 fake 模式需 KYLIN_LLM_FAKE=true.
    """
    monkeypatch.setenv("KYLIN_LLM_RECORD", "false")
    monkeypatch.setenv("KYLIN_LLM_FAKE", "true")

    origin = _resolved_via_lifespan()
    assert origin == "fake_closure", f"KYLIN_LLM_FAKE=true 应返 fake_closure, got {origin!r}"
