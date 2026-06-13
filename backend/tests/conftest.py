"""测试全局夹具（pytest 自动发现）。

测试卫生（审阅决策③派生）：app lifespan 默认把审计库落 ./data/audit.db（真文件，跨运行累积、
污染工作树）。本 autouse 夹具把 `_AUDIT_DB_PATH` 指向 :memory:，使任何经 lifespan 的测试都用
内存审计库，杜绝在工作树落地 audit.db。需真文件库的测试可在用例内再行覆盖。
"""

from __future__ import annotations

import pytest

from backend.app.api import app as app_module


@pytest.fixture(autouse=True)
def _isolate_audit_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """把审计库路径钉到 :memory:，避免测试在工作树落地 audit.db。"""
    monkeypatch.setattr(app_module, "_AUDIT_DB_PATH", ":memory:")
