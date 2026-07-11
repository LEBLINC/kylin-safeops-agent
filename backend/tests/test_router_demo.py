"""L 域 /api/demo/* 3 用例（commit 4 增量）。

覆盖：
1. POST /api/demo/{scenario}/prepare → admin 调 A 场景返 ready=True
2. POST /api/demo/{scenario}/run → 非 admin 必 403
3. POST /api/demo/{scenario}/prepare → KYLIN_SANDBOX_ENABLED=1 时拒
"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from backend.app.api.app import create_app
from backend.app.api.auth import Principal
from backend.app.api.deps import require_proxy_identity


def _admin() -> Principal:
    return Principal(user="admin", roles=frozenset({"admin"}))


def _operator() -> Principal:
    return Principal(user="operator", roles=frozenset({"operator"}))


def _viewer() -> Principal:
    return Principal(user="viewer", roles=frozenset({"viewer"}))


def _setup(p: Principal) -> TestClient:
    app = create_app()
    app.dependency_overrides[require_proxy_identity] = lambda: p
    return TestClient(app)


def test_demo_prepare_admin_returns_ready() -> None:
    """admin 调 /api/demo/A/prepare 返 ready=True + audit_db_path。"""
    with _setup(_admin()) as client:
        resp = client.post("/api/demo/A/prepare")
        assert resp.status_code == 200
        body = resp.json()
        assert body["scenario"] == "A"
        assert body["ready"] is True
        assert body["by"] == "admin"
        assert "audit_db_path" in body
        assert body["audit_db_path"].endswith("audit.db")


def test_demo_run_non_admin_returns_403() -> None:
    """operator / viewer 调 /api/demo/A/run 必 403（防 demo 污染审计库：admin-only）。"""
    with _setup(_operator()) as client:
        resp = client.post("/api/demo/A/run")
        assert resp.status_code == 403
        assert "admin" in resp.json()["detail"]
    with _setup(_viewer()) as client:
        resp = client.post("/api/demo/A/run")
        assert resp.status_code == 403
    # admin 调（场景 A 调真依赖 orchestrator + 真 audit，可能耗时/失败，
    # 但 admin 校验通过，404/500/200 都算 RBAC 通过——这里只验证 RBAC：模拟 prepare 即可）
    with _setup(_admin()) as client:
        resp = client.post("/api/demo/A/prepare")
        assert resp.status_code == 200


def test_demo_sandbox_enabled_rejects() -> None:
    """KYLIN_SANDBOX_ENABLED=1 时 admin 也必 409（沙箱环境不允许 demo 改审计库）。"""
    os.environ["KYLIN_SANDBOX_ENABLED"] = "1"
    try:
        with _setup(_admin()) as client:
            resp = client.post("/api/demo/A/prepare")
            assert resp.status_code == 409
            assert "KYLIN_SANDBOX_ENABLED" in resp.json()["detail"]
            resp = client.post("/api/demo/A/run")
            assert resp.status_code == 409
            resp = client.post("/api/demo/A/cleanup")
            assert resp.status_code == 409
    finally:
        os.environ.pop("KYLIN_SANDBOX_ENABLED", None)
