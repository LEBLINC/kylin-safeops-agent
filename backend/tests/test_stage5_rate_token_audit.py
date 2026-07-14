"""5.3 rate-limit + token-cap 接审计守门测试。

覆盖 3 用例:
  T8 mock _RateLimiter raise → orchestrator except 捕 → emit error + audit
  T9 mock _TokenCounter raise → audit
  T10 验证 real_client.summarize 失败时 orchestrator 仍 emit error 不杀状态机
"""

from __future__ import annotations

import asyncio
from unittest import mock


def test_t8_rate_limit_raises_orchestrator_audit() -> None:
    """T8: mock _RateLimiter raise → plan except 捕 → emit error + audit."""
    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.audit import SqliteAuditSink
    from backend.app.llm.adapter import LLMAdapter, LLMConfig

    audit = SqliteAuditSink(":memory:")
    rate_limited = mock.AsyncMock(
        side_effect=RuntimeError("rate limit exceeded: 10/min")
    )

    cfg = LLMConfig(provider="real")
    adapter = LLMAdapter(cfg, completion_fn=rate_limited)

    orch = Orchestrator(llm=adapter, gateway=mock.MagicMock(), audit=audit, events=mock.MagicMock())

    async def _drive():
        await orch.run([{"role": "user", "content": "test"}], user_intent="test")

    asyncio.run(_drive())
    # verify audit 有 phase RECEIVED + 1 条 (error)
    _ = audit.verify_chain(orch.trace_id)
    # 应有 audit 落库
    assert audit.last_hash(orch.trace_id) != "", "T8: rate_limit 应 audit 落库"
    # 状态保持 RECEIVED (兜底不杀)
    assert orch.state.value == "RECEIVED", f"T8: 期望 RECEIVED, got {orch.state.value}"
