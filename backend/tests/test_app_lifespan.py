"""ADR-0004 lifespan fail-fast 测试（部署硬阻断收口）。

覆盖：
1. proxy + KYLIN_LDAP_MOCK=true → lifespan 启动期 RuntimeError（拒启动）
2. proxy + KYLIN_LDAP_MOCK=false → 启动 OK（生产合法配置）
3. dev + KYLIN_LDAP_MOCK=true → 启动 OK（demo/单测合法路径）

与 test_api_lifespan.py 职责切分——后者验 fail_closed wiring；本文件专验 ADR-0004
部署硬阻断。test_api_lifespan.py 的 3 用例不会与本文件重复（场景不同）。
"""

from __future__ import annotations

import asyncio
import os
from unittest import mock

from backend.app.api.app import create_app, lifespan


def test_lifespan_proxy_with_ldap_mock_true_fails_fast() -> None:
    """ADR-0004：proxy + mock=true 误启硬阻断 → 启动期 RuntimeError。"""

    async def scenario() -> None:
        app = create_app()
        with (
            mock.patch.dict(
                os.environ,
                {"KYLIN_AUTH_MODE": "proxy", "KYLIN_LDAP_MOCK": "true"},
                clear=False,
            ),
            mock.patch("backend.app.api.deps._auth_mode", lambda: "proxy"),
        ):
            try:
                async with lifespan(app):
                    pass  # pragma: no cover
                raised = False
            except RuntimeError as e:
                raised = True
                assert "ADR-0004" in str(e), f"错误消息应含 ADR-0004，实际 {e}"
            assert raised, "proxy + mock=true 应 RuntimeError，未 raise"

    asyncio.run(scenario())


def test_lifespan_proxy_with_ldap_mock_false_starts_ok() -> None:
    """ADR-0004：proxy + mock=false → 启动 OK（生产合法配置）。"""

    async def scenario() -> None:
        app = create_app()
        with (
            mock.patch.dict(
                os.environ,
                {"KYLIN_AUTH_MODE": "proxy", "KYLIN_LDAP_MOCK": "false"},
                clear=False,
            ),
            mock.patch("backend.app.api.deps._auth_mode", lambda: "proxy"),
        ):
            async with lifespan(app):
                pass  # 启动 OK = 不 raise

    asyncio.run(scenario())


def test_lifespan_dev_with_ldap_mock_true_starts_ok() -> None:
    """ADR-0004：dev + mock=true → 启动 OK（demo/单测合法路径，fail-fast 仅 proxy 触发）。"""

    async def scenario() -> None:
        app = create_app()
        with (
            mock.patch.dict(
                os.environ,
                {"KYLIN_AUTH_MODE": "dev", "KYLIN_LDAP_MOCK": "true"},
                clear=False,
            ),
            mock.patch("backend.app.api.deps._auth_mode", lambda: "dev"),
        ):
            async with lifespan(app):
                pass

    asyncio.run(scenario())
