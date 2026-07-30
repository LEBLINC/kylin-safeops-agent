"""步骤 0：lifespan fail_closed 接线回归。

安全层 7b74404 / 94bdac9 已给 `connect(..., fail_closed=...)` 加上参数 + 测试；
编排层直到阶段5 才在 `app.py lifespan` 把 `KYLIN_AUTH_MODE=="proxy"` 接到
`connect(fail_closed=True)`。本文件固化此接线。

- proxy 模式（生产）→ fail_closed=True（chmod 失败 raise，拒启动）；
- dev 模式（联调）→ fail_closed=False（chmod 失败仅 log，零回归）；
- :memory: 测试夹具：lifespan 不调 connect（SqliteAuditSink 内部 connect 自动跳）。

Spy 目标必须是 `app._db_connect`（module-level 导入后绑定到 app module 的属性），
**不是** `backend.app.db.session.connect`（lifespan 走的是 app module 属性）。
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from unittest import mock

from backend.app.api import app as app_module
from backend.app.api.app import create_app, lifespan
from backend.app.audit import SqliteAuditSink
from backend.app.db import session as session_mod


def _spy_connect(captured: dict) -> mock.Mock:
    """spy 包装 session_mod.connect：调用真函数但记录 kwargs。"""

    def fake_connect(
        db_path: str,
        *,
        fail_closed: bool = False,
    ) -> sqlite3.Connection:
        captured["fail_closed"] = fail_closed
        captured["db_path"] = db_path
        return session_mod.connect(db_path, fail_closed=fail_closed)

    return fake_connect


# ---- 1. proxy 模式 → fail_closed=True --------------------------------------


def test_lifespan_proxy_passes_fail_closed_true() -> None:
    """proxy 模式（KYLIN_AUTH_MODE=proxy）→ lifespan 调 connect(fail_closed=True)。"""

    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "audit.db")
            app_module._AUDIT_DB_PATH = db_path  # type: ignore[attr-defined]
            captured: dict = {}

            app = create_app()
            # spy app._db_connect（module-level import 后的属性）
            # 同时 mock app._auth_mode（deps._auth_mode 是函数；app.py lifespan 调
            # `from backend.app.api.deps import _auth_mode` 是局部 import；每次重新解析
            # 属性查找），所以直接 mock backend.app.api.deps._auth_mode 即可生效。
            with (
                mock.patch.object(app_module, "_db_connect", side_effect=_spy_connect(captured)),
                mock.patch("backend.app.api.deps._auth_mode", lambda: "proxy"),
            ):
                async with lifespan(app):
                    audit = app_module.get_audit()
                    assert isinstance(audit, SqliteAuditSink)
            assert (
                captured.get("fail_closed") is True
            ), f"proxy 模式应传 fail_closed=True，实际 {captured!r}"

    asyncio.run(scenario())


# ---- 2. dev 模式 → fail_closed=False ---------------------------------------


def test_lifespan_dev_passes_fail_closed_false() -> None:
    """dev 模式（KYLIN_AUTH_MODE=dev，conftest 默认）→ lifespan 调 connect(fail_closed=False)。"""

    async def scenario() -> None:
        # conftest 已 monkeypatch KYLIN_AUTH_MODE=dev；测试再设一次确保不被其他测试改动
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "audit.db")
            app_module._AUDIT_DB_PATH = db_path  # type: ignore[attr-defined]
            captured: dict = {}

            app = create_app()
            with mock.patch.object(app_module, "_db_connect", side_effect=_spy_connect(captured)):
                async with lifespan(app):
                    audit = app_module.get_audit()
                    assert isinstance(audit, SqliteAuditSink)
            assert (
                captured.get("fail_closed") is False
            ), f"dev 模式应传 fail_closed=False，实际 {captured!r}"

    asyncio.run(scenario())


# ---- 3. :memory: 短路 → 不调 connect ---------------------------------------


def test_lifespan_memory_short_circuit() -> None:
    """:memory: 路径 → lifespan 短路不走 connect（让 SqliteAuditSink 内部 connect 自动跳）。"""

    async def scenario() -> None:
        app_module._AUDIT_DB_PATH = ":memory:"  # type: ignore[attr-defined]
        captured: dict = {}

        app = create_app()
        with mock.patch.object(app_module, "_db_connect", side_effect=_spy_connect(captured)):
            async with lifespan(app):
                audit = app_module.get_audit()
                assert isinstance(audit, SqliteAuditSink)
        assert not captured, f":memory: 短路，lifespan 不应调 connect，实际 {captured!r}"

    asyncio.run(scenario())
