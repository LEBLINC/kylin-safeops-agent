"""/api/approvals router 5 用例（commit 1 增量）。

覆盖：
1. GET /api/approvals?status=pending → 列（空状态返 []）
2. GET /api/approvals/{trace_id} → 详情（不存在 404）
3. POST /api/approvals/{trace_id}/approve → 走 resume_approval 路径（404 when no session）
4. POST /api/approvals/{trace_id}/reject → 任何已认证者（同样 404）
5. POST /api/approvals/{trace_id}/escalate → admin-only（operator/viewer 必 403）
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api.app import create_app, get_audit
from backend.app.api.auth import Principal
from backend.app.api.deps import require_proxy_identity
from backend.app.audit import SqliteAuditSink


def _admin() -> Principal:
    return Principal(user="admin", roles=["admin"])


def _viewer() -> Principal:
    return Principal(user="viewer", roles=["viewer"])


def _operator() -> Principal:
    return Principal(user="operator", roles=["operator"])


def _setup(p: Principal) -> TestClient:
    """装配 TestClient：审计库 :memory: + dev 联调态（conftest 已默认）+ 主参 override。"""
    app = create_app()
    app.dependency_overrides[get_audit] = lambda: SqliteAuditSink(":memory:")
    app.dependency_overrides[require_proxy_identity] = lambda: p
    return TestClient(app)


def test_approval_list_pending_empty() -> None:
    """空 SessionRegistry → list 返 {items: [], total: 0}。"""
    with _setup(_admin()) as client:
        resp = client.get("/api/approvals", params={"status": "pending"})
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}


def test_approval_detail_not_found_404() -> None:
    """trace 不存在 → 404 + 明确 detail。"""
    with _setup(_admin()) as client:
        resp = client.get("/api/approvals/does-not-exist")
        assert resp.status_code == 404
        assert "unknown trace_id" in resp.json()["detail"]


def test_approval_approve_no_session_returns_404() -> None:
    """approve 走 resume_approval 路径——trace 不存在时返 404（session lookup 优先于 RBAC）。"""
    with _setup(_admin()) as client:
        resp = client.post("/api/approvals/missing/approve")
        assert resp.status_code == 404


def test_approval_reject_any_authenticated_principal() -> None:
    """reject 端点仅需已认证，不校验 role——viewer 可调（同样 404 by no session）。"""
    with _setup(_viewer()) as client:
        resp = client.post("/api/approvals/missing/reject")
        assert resp.status_code == 404


def test_approval_escalate_admin_only() -> None:
    """escalate 端点 admin-only：operator/viewer 必 403，admin 调时 trace 不存在 → 404。"""
    with _setup(_operator()) as client:
        resp = client.post("/api/approvals/missing/escalate", json={"to_user": "alice"})
        assert resp.status_code == 403
        assert "admin" in resp.json()["detail"]
    with _setup(_viewer()) as client:
        resp = client.post("/api/approvals/missing/escalate", json={"to_role": "admin"})
        assert resp.status_code == 403
    with _setup(_admin()) as client:
        resp = client.post("/api/approvals/missing/escalate", json={"to_user": "alice"})
        assert resp.status_code == 404


def test_to_item_value_domain_contract() -> None:
    """之七十二：_to_item 值域契约（前端 RiskTag/formatTime 消费口径）。

    - risk_level 必须是 R 级（operator→R2 / admin→R3 / 非 WAIT→R0），
      不得把 approval_role 字符串原样塞入；
    - created_at 必须是 ISO 字符串（epoch float 转换），不得是 str(time.time())。
    """
    from types import SimpleNamespace

    from backend.app.api.routers.approvals import _to_item

    def _session(state: str, role: str | None, created: float) -> SimpleNamespace:
        orch = SimpleNamespace(
            user_intent="清理日志",
            state=SimpleNamespace(value=state),
            pending_approval_role=role,
        )
        return SimpleNamespace(trace_id="t-1", orchestrator=orch, created_at=created)

    epoch = 1752650000.0
    item = _to_item(_session("WAIT_APPROVAL", "operator", epoch))
    assert item.risk_level == "R2"
    assert item.approval_role == "operator"
    assert item.created_at.startswith("2025") or item.created_at.startswith("2026")
    assert "T" in item.created_at  # ISO 格式，非 str(time.time())

    assert _to_item(_session("WAIT_APPROVAL", "admin", epoch)).risk_level == "R3"
    # 非 WAIT_APPROVAL：role 不取、risk 归 R0
    finished = _to_item(_session("FINISHED", "admin", epoch))
    assert finished.risk_level == "R0"
    assert finished.approval_role is None
