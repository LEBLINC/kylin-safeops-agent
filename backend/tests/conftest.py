"""测试全局夹具（pytest 自动发现）。

测试卫生（审阅决策③派生）：app lifespan 默认把审计库落 ./data/audit.db（真文件，跨运行累积、
污染工作树）。本 autouse 夹具把 `_AUDIT_DB_PATH` 指向 :memory:，使任何经 lifespan 的测试都用
内存审计库，杜绝在工作树落地 audit.db。需真文件库的测试可在用例内再行覆盖。

认证模式（接线增量·任务甲）：生产默认 `KYLIN_AUTH_MODE=proxy`（强制反代签名身份，fail-closed）。
为不切断大量经 `X-User-Role` 驱动审批续跑的既有/联调测试，本夹具把测试默认钉到 `dev` 模式
（演示态裸头）。**验证 proxy 模式（签名身份）的测试在用例内 monkeypatch 覆盖回 `proxy`**。
生产默认仍是 proxy（仅测试默认 dev）。
"""

from __future__ import annotations

import pytest

from backend.app.api import app as app_module


@pytest.fixture(autouse=True)
def _test_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """审计库钉 :memory:（杜绝 audit.db 落工作树）+ 认证默认 dev 模式（proxy 测试自行覆盖）。"""
    monkeypatch.setattr(app_module, "_AUDIT_DB_PATH", ":memory:")
    monkeypatch.setenv("KYLIN_AUTH_MODE", "dev")
