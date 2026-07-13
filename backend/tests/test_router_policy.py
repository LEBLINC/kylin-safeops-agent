"""L 域 /api/policy/* 3 用例（commit 3 增量）。

覆盖：
1. GET /api/policy/rules → DEFAULT_POLICY 非空（CMD001 等规则）
2. GET /api/policy/events → 空 audit 库返空 events
3. GET /api/policy/risk-levels → 必须含 R0/R1/R2/R3 4 档
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api.app import create_app, get_audit
from backend.app.api.auth import Principal
from backend.app.api.deps import require_proxy_identity
from backend.app.audit import SqliteAuditSink


def _admin() -> Principal:
    return Principal(user="admin", roles=frozenset({"admin"}))


def _setup() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_audit] = lambda: SqliteAuditSink(":memory:")
    app.dependency_overrides[require_proxy_identity] = lambda: _admin()
    return TestClient(app)


def test_policy_rules_returns_default_policy() -> None:
    """DEFAULT_POLICY 含规则 → /api/policy/rules 返 list[PolicyRuleOut]。"""
    with _setup() as client:
        resp = client.get("/api/policy/rules", headers={"X-User-Role": "auditor"})
        assert resp.status_code == 200
        body = resp.json()
        assert "rules" in body
        assert isinstance(body["rules"], list)
        assert len(body["rules"]) > 0
        # 至少含一条规则（DEFAULT_POLICY 至少有 FILE001 / CMD001 等）
        ids = {r["id"] for r in body["rules"]}
        assert any(rid.startswith("CMD") or rid.startswith("FILE") for rid in ids)
        # version 字段是 int >= 1
        assert isinstance(body["version"], int)
        assert body["version"] >= 1


def test_policy_events_empty_audit_returns_empty_list() -> None:
    """空 audit 库 → /api/policy/events 返 {items: [], total: 0}。"""
    with _setup() as client:
        resp = client.get("/api/policy/events", headers={"X-User-Role": "auditor"})
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"items": [], "total": 0}


def test_policy_risk_levels_has_R0_R1_R2_R3() -> None:
    """风险等级硬编码字典必含 R0/R1/R2/R3 4 档 + 审批要求。"""
    with _setup() as client:
        resp = client.get("/api/policy/risk-levels", headers={"X-User-Role": "auditor"})
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        levels = {it["level"] for it in items}
        assert levels == {"R0", "R1", "R2", "R3"}
        # R2 需 operator / R3 需 admin（决策⑬ RBAC fail-closed）
        by_level = {it["level"]: it for it in items}
        assert by_level["R0"]["auto_approve"] is True
        assert by_level["R1"]["auto_approve"] is True
        assert by_level["R2"]["auto_approve"] is False
        assert by_level["R2"]["approval_role_required"] == "operator"
        assert by_level["R3"]["auto_approve"] is False
        assert by_level["R3"]["approval_role_required"] == "admin"
