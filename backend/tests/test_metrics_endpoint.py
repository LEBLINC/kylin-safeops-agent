"""C1（阶段6 第二梯队）：自研 metrics 系统守门测试。

覆盖 3 用例：
  T1 counter 累加正确（Metrics.inc 多次调用求和）
  T2 GET /api/system/metrics 返回结构（counters/gauges 两个字典）
  T3 认证闸生效（proxy 模式缺签名头 → 401，不裸暴露指标）
"""

from __future__ import annotations

import asyncio

import httpx

from backend.app.agent.metrics import Metrics, get_metrics
from backend.app.api.app import create_app


def test_t1_counter_accumulates_correctly() -> None:
    """T1: Metrics.inc 多次调用正确累加（含默认 amount=1 与显式 amount）。"""
    m = Metrics()
    m.inc("x")
    m.inc("x")
    m.inc("x", amount=3)
    assert m.snapshot()["counters"]["x"] == 5

    m.set_gauge("y", 1.5)
    m.set_gauge("y", 2.5)
    assert m.snapshot()["gauges"]["y"] == 2.5


def test_t2_metrics_endpoint_returns_structure(monkeypatch) -> None:
    """T2: GET /api/system/metrics dev 模式放行 → 200 + counters/gauges 两键。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "dev")
    get_metrics().reset()
    get_metrics().inc("orchestrator.state.RECEIVED")

    async def _run():
        app = create_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await c.get("/api/system/metrics")

    resp = asyncio.run(_run())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "counters" in data
    assert "gauges" in data
    assert data["counters"]["orchestrator.state.RECEIVED"] >= 1


def test_t3_metrics_endpoint_requires_auth(monkeypatch) -> None:
    """T3: proxy 模式缺签名头 → 401（不裸暴露指标端点）。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", "test-secret-t3")

    async def _run():
        app = create_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await c.get("/api/system/metrics")

    resp = asyncio.run(_run())
    assert resp.status_code == 401, f"T3 期望 401, got {resp.status_code}: {resp.text}"
