"""B4 commit 3 守门测试: /api/system/ready readiness 端点。

覆盖 2 用例:
  T5 test_health_ready_returns_200: 三组件存活 → 200 + ready=True
  T6 test_health_db_failure_returns_503: audit.ping() raise → 503 + ready=False
"""

from __future__ import annotations

import asyncio
from unittest import mock

import httpx

from backend.app.api.app import create_app, lifespan


def test_t5_health_ready_returns_200() -> None:
    """T5: 三组件存活 → readiness 返 200 + ready=True."""
    from backend.app.api.event_bus import EventBus
    from backend.app.api.session_registry import SessionRegistry

    async def _run():
        async with lifespan(create_app()):
            app = create_app()
            # 替换 deps: audit.ping OK / bus active / registry empty
            fake_audit = mock.MagicMock()
            fake_audit.ping.return_value = True
            fake_bus = EventBus()
            fake_registry = SessionRegistry()
            from backend.app.api.app import get_audit, get_bus, get_registry

            app.dependency_overrides[get_audit] = lambda: fake_audit
            app.dependency_overrides[get_bus] = lambda: fake_bus
            app.dependency_overrides[get_registry] = lambda: fake_registry
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                return await c.get("/api/system/ready")

    resp = asyncio.run(_run())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ready"] is True
    assert data["db"] is True
    assert data["bus"] is True
    assert data["registry"] is True


def test_t6_health_db_failure_returns_503() -> None:
    """T6: audit.ping() raise → readiness 返 503 + ready=False."""
    from backend.app.api.event_bus import EventBus
    from backend.app.api.session_registry import SessionRegistry

    async def _run():
        async with lifespan(create_app()):
            app = create_app()
            fake_audit = mock.MagicMock()
            fake_audit.ping.side_effect = RuntimeError("db connection lost")
            fake_bus = EventBus()
            fake_registry = SessionRegistry()
            from backend.app.api.app import get_audit, get_bus, get_registry

            app.dependency_overrides[get_audit] = lambda: fake_audit
            app.dependency_overrides[get_bus] = lambda: fake_bus
            app.dependency_overrides[get_registry] = lambda: fake_registry
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                return await c.get("/api/system/ready")

    resp = asyncio.run(_run())
    assert resp.status_code == 503, resp.text
    data = resp.json()
    assert data["ready"] is False
    assert data["db"] is False
