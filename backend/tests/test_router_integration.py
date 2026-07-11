"""L 域 4 Router 联调测试（commit 5 增量）。

验证：
1. 4 router 全挂载（approvals/audit/policy/demo 都注册到 api_router）
2. OpenAPI schema 含全部 endpoint（含 4 Router 的 15 个新端点）
3. 跨 router smoke：4 router 的 minimal endpoint 都能 200/4xx（不返 500）
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api.app import create_app, get_audit
from backend.app.api.auth import Principal
from backend.app.api.deps import require_proxy_identity
from backend.app.api.routers import api_router
from backend.app.audit import SqliteAuditSink


def _admin() -> Principal:
    return Principal(user="admin", roles=frozenset({"admin"}))


def _setup() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_audit] = lambda: SqliteAuditSink(":memory:")
    app.dependency_overrides[require_proxy_identity] = lambda: _admin()
    return TestClient(app)


def test_all_routers_mounted_on_app() -> None:
    """api_router 包含 4 个新 router 的 routes。

    走 route.path 提取 prefix（APIRouter.include_router 时 prefix 会拼到 path 前）。
    """
    prefixes: set[str] = set()
    for route in api_router.routes:
        path = getattr(route, "path", "").lstrip("/")
        # path 形如 api/approvals/resume → prefix api/approvals
        parts = path.split("/")
        if len(parts) >= 2:
            prefixes.add("/" + "/".join(parts[:2]))
    # 至少含 4 个目标 prefix
    assert "/api/approvals" in prefixes
    assert "/api/audit" in prefixes
    assert "/api/policy" in prefixes
    assert "/api/demo" in prefixes


def test_app_openapi_has_all_new_endpoints() -> None:
    """OpenAPI schema 含 4 router 的所有 endpoint 路径。"""
    with _setup() as client:
        schema = client.get("/openapi.json").json()
        paths = schema.get("paths", {})
        expected_paths = {
            "/api/approvals": {"GET"},
            "/api/approvals/{trace_id}": {"GET"},
            "/api/approvals/{trace_id}/approve": {"POST"},
            "/api/approvals/{trace_id}/reject": {"POST"},
            "/api/approvals/{trace_id}/escalate": {"POST"},
            "/api/audit/traces": {"GET"},
            "/api/audit/traces/{trace_id}": {"GET"},
            "/api/audit/verify": {"POST"},
            "/api/audit/traces/{trace_id}/export": {"GET"},
            "/api/policy/rules": {"GET"},
            "/api/policy/events": {"GET"},
            "/api/policy/risk-levels": {"GET"},
            "/api/demo/{scenario}/prepare": {"POST"},
            "/api/demo/{scenario}/run": {"POST"},
            "/api/demo/{scenario}/cleanup": {"POST"},
        }
        for path, methods in expected_paths.items():
            assert path in paths, f"OpenAPI 缺 endpoint: {path}"
            actual_methods = {m.upper() for m in paths[path].keys()}
            assert methods <= actual_methods, f"OpenAPI {path} 缺 methods: {methods - actual_methods}"


def test_cross_router_smoke_no_500() -> None:
    """4 router 的 minimal endpoint 都能返 200/4xx（绝不返 500）。"""
    with _setup() as client:
        # approvals: list + 详情（404 OK）
        assert client.get("/api/approvals").status_code == 200
        assert client.get("/api/approvals/missing").status_code == 404
        # audit: list + 详情 + verify + export（404 OK）
        assert client.get("/api/audit/traces").status_code == 200
        assert client.get("/api/audit/traces/missing").status_code == 404
        assert client.post("/api/audit/verify?trace_id=missing").status_code == 200
        assert client.get("/api/audit/traces/missing/export").status_code == 404
        # policy: rules + events + risk-levels（200 OK）
        assert client.get("/api/policy/rules").status_code == 200
        assert client.get("/api/policy/events").status_code == 200
        assert client.get("/api/policy/risk-levels").status_code == 200
        # demo: prepare + run（200 OK，admin 调），cleanup（200 OK）
        assert client.post("/api/demo/A/prepare").status_code == 200
        # 注：/run 不实际调，避免依赖 orchestrator 真审计库；只验证 prepare/cleanup 通过
        assert client.post("/api/demo/A/cleanup").status_code == 200