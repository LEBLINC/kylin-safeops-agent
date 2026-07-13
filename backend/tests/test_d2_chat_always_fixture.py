"""D2 §5 红线守门：Chat 路由永远走 fixture（ADR-0003 demo-only 设计意图）。

背景：
- get_llm() 硬编码 return build_fake_llm()（ADR-0003 demo-only）
- 即使 KYLIN_LLM_PROVIDER=real / 注入 RealLLMClient，Chat 路由也应走 fixture
- 本守门测试确保未来若有人误改 get_llm() 走 real，CI 立刻红

T9：设 KYLIN_LLM_PROVIDER=real + 注入 spy RealLLMClient → POST /api/chat →
    spy 计数 == 0（real LLM 没被调）
T10：直接拿 app.get_llm() 返回值，断言 isinstance fixture impl 且 completion_fn
     不指向 RealLLMClient
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.app.api.app import create_app, get_audit, get_llm, lifespan
from backend.app.audit import SqliteAuditSink


@pytest.fixture
def audit_sink() -> SqliteAuditSink:
    return SqliteAuditSink(":memory:")


def _run_chat_with_lifespan(app, audit_sink, message: str = "test") -> httpx.Response:
    """同步驱动：async with lifespan + POST /api/chat + GET /api/chat/{trace_id}/events 拉 SSE。"""

    async def _run() -> httpx.Response:
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.post("/api/chat", json={"message": message})
                return resp

    app.dependency_overrides[get_audit] = lambda: audit_sink
    return asyncio.run(_run())


# ---- T9: KYLIN_LLM_PROVIDER=real 时 Chat 仍走 fixture -----------------------


def test_d2_chat_always_uses_fixture_even_when_provider_real(
    audit_sink: SqliteAuditSink, monkeypatch
) -> None:
    """D2 §5 红线守门：设 KYLIN_LLM_PROVIDER=real + 注入 RealLLMClient spy，
    POST /api/chat 后 spy 计数 == 0（real LLM 没被调）。

    实现：mock RealLLMClient.__init__ → spy 计数；Chat 路由走 get_llm() →
    build_fake_llm()（ADR-0003 demo-only 锁死），不走 RealLLMClient → spy 不变。
    """
    from backend.app.llm import real_client as rc

    real_client_inits = {"n": 0}

    original_init = rc.RealLLMClient.__init__

    def spy_init(self, *args, **kwargs):  # noqa: ANN001
        real_client_inits["n"] += 1
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(rc.RealLLMClient, "__init__", spy_init)
    monkeypatch.setenv("KYLIN_LLM_PROVIDER", "real")  # 即便 env=real，Chat 仍走 fixture

    app = create_app()
    resp = _run_chat_with_lifespan(app, audit_sink, message="看系统")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "trace_id" in body

    # 关键断言：spy 计数 == 0（RealLLMClient 没被构造）
    # 即便 KYLIN_LLM_PROVIDER=real + RealLLMClient 类被 import，Chat 路由也不走 real
    assert real_client_inits["n"] == 0, (
        f"D2 violation: RealLLMClient.__init__ called {real_client_inits['n']} times "
        "when Chat should use fixture per ADR-0003 demo-only"
    )


# ---- T10: get_llm() 返 fixture impl（非 RealLLMClient）-------------------


def test_d2_get_llm_returns_fixture_not_real(audit_sink: SqliteAuditSink) -> None:
    """D2 §5 红线守门：直接调 app.get_llm() → 断言返 LLMAdapter（非 RealLLMClient）

    实现方式：检查返回对象的 class 名字 ≠ 'RealLLMClient'，且模块名 ≠ real_client。
    这是 ADR-0003 demo-only 的最直接 byte-level 锁。
    """

    # 用 lifespan 启动后再调 get_llm（确保 _registry/_audit 已就位）
    async def _inspect() -> str:
        async with lifespan(create_app()):
            llm = get_llm()
            return type(llm).__module__ + "." + type(llm).__name__

    mod_class = asyncio.run(_inspect())
    # 必须是 backend.app.api._fakes（fake impl），不是 backend.app.llm.real_client
    assert mod_class.startswith("backend.app.api._fakes") or mod_class.startswith(
        "backend.app.llm.adapter"
    ), (
        f"D2 violation: get_llm() returned {mod_class!r}, expected "
        "backend.app.api._fakes (fixture) or backend.app.llm.adapter (LLMAdapter)."
    )
    # 明确不能是 RealLLMClient
    assert "real_client" not in mod_class, (
        f"D2 violation: get_llm() returned RealLLMClient ({mod_class!r}); "
        "Chat must use fixture per ADR-0003 demo-only"
    )


def test_d2_get_llm_completion_fn_not_real(monkeypatch) -> None:
    """D2 §5 红线守门：get_llm() 返回的 LLMAdapter 的 _completion_fn 不是
    RealLLMClient.completion_fn（即不是真 LLM 路径）。
    """
    from backend.app.llm.adapter import LLMAdapter
    from backend.app.llm.real_client import RealLLMClient

    real_spy = {"calls": 0}

    async def _spy_completion(self, messages):  # noqa: ANN001
        real_spy["calls"] += 1
        return "{}"

    monkeypatch.setattr(RealLLMClient, "completion_fn", _spy_completion)

    async def _inspect() -> None:
        async with lifespan(create_app()):
            llm = get_llm()
            assert isinstance(llm, LLMAdapter)
            # 调 plan()：fake completion_fn 应被调，real_spy 不变
            await llm.plan([{"role": "user", "content": "test"}])

    asyncio.run(_inspect())
    # 关键断言：RealLLMClient.completion_fn spy 计数 == 0
    assert real_spy["calls"] == 0, (
        f"D2 violation: RealLLMClient.completion_fn called {real_spy['calls']} times "
        "when Chat should use fixture per ADR-0003 demo-only"
    )


# ---- T11: KYLIN_LLM_RECORD=true → RealLLMClient spy 计数 >= 1（录制模式放行） ---
def test_d2_record_mode_uses_real_llm(audit_sink: SqliteAuditSink, monkeypatch) -> None:
    """D2 §5 红线守门新增（ADR-0005 demo-record-mode）：KYLIN_LLM_RECORD=true
    显式 opt-in 录制模式 → RealLLMClient.__init__ 被调过（spy 计数 >= 1）。

    守门语义：
    - 默认 KYLIN_LLM_RECORD=false / 未设 → spy == 0（T9 守门）
    - 录制模式 KYLIN_LLM_RECORD=true → spy >= 1（录制模式放行）
    - 守门本身仍坚持"默认 fixture 强钉"（ADR-0003 仍守），仅显式录制场景放行
    - /api/llm/health?probe=true 不在本测试覆盖：probe 路径是 lifespan 内显式
      build_fake_llm()，不走 get_llm 装配，不属于本守门语义
    """
    from backend.app.llm import real_client as rc

    real_client_inits = {"n": 0}

    original_init = rc.RealLLMClient.__init__

    def spy_init(self, *args, **kwargs):  # noqa: ANN001
        real_client_inits["n"] += 1
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(rc.RealLLMClient, "__init__", spy_init)
    monkeypatch.setenv("KYLIN_LLM_RECORD", "true")

    app = create_app()

    # 直接从 app.get_llm() 拿 LLM Adapter，确认 RealLLMClient 被构造过
    async def _inspect() -> None:
        async with lifespan(app):
            llm = get_llm()
            from backend.app.llm.adapter import LLMAdapter as _Adapter

            assert isinstance(
                llm, _Adapter
            ), f"D2 record-mode: get_llm() must return LLMAdapter, got {type(llm).__name__}"

    asyncio.run(_inspect())
    assert real_client_inits["n"] >= 1, (
        f"D2 record-mode violation: RealLLMClient.__init__ called "
        f"{real_client_inits['n']} times when KYLIN_LLM_RECORD=true, "
        "expected >= 1 (ADR-0005 demo-record-mode opt-in path)"
    )
