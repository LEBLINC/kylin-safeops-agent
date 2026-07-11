"""L 域 /api/audit/* 4 用例（commit 2 增量）。

覆盖：
1. GET /api/audit/traces → 空库返空 list
2. GET /api/audit/traces/{trace_id} → 详情（不存在 404）
3. POST /api/audit/verify → 整链 valid（空 trace_id 返 valid=True + record_count=0）
4. GET /api/audit/traces/{trace_id}/export → S9 过滤（敏感字段不在 response）
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.app.api.app import create_app, get_audit
from backend.app.api.auth import Principal
from backend.app.api.deps import require_proxy_identity
from backend.app.audit import SqliteAuditSink
from backend.app.contracts.audit import GENESIS_HASH, AuditRecord, compute_curr_hash


def _admin() -> Principal:
    return Principal(user="admin", roles=frozenset({"admin"}))


def _setup(p: Principal) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_audit] = lambda: SqliteAuditSink(":memory:")
    app.dependency_overrides[require_proxy_identity] = lambda: p
    return TestClient(app)


def _seed_one_trace(sink: SqliteAuditSink) -> None:
    """写一条 trace 含敏感字段（验证 S9 过滤 + verify_chain valid）。"""
    payload = {
        "user_intent": "查看磁盘占用",
        "api_key": "sk-test-SHOULD-NOT-APPEAR-IN-RESPONSE",
        "authorization": "Bearer SHOULD-NOT-APPEAR",
        "password": "secret123-SHOULD-NOT-APPEAR",
    }
    prev = GENESIS_HASH
    curr = compute_curr_hash(prev, payload)
    sink.append(
        AuditRecord(
            trace_id="t1",
            seq=0,
            phase="RECEIVED",
            payload=payload,
            prev_hash=prev,
            curr_hash=curr,
        )
    )


def test_audit_list_empty_returns_empty_list() -> None:
    """空审计库 → /api/audit/traces 返 {items: [], total: 0, limit, offset}。"""
    with _setup(_admin()) as client:
        resp = client.get("/api/audit/traces")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["limit"] == 50
        assert body["offset"] == 0


def test_audit_detail_unknown_trace_returns_404() -> None:
    """trace 不存在 → 404 + 明确 detail（不返 500）。"""
    with _setup(_admin()) as client:
        resp = client.get("/api/audit/traces/does-not-exist")
        assert resp.status_code == 404
        assert "unknown trace_id" in resp.json()["detail"]


def test_audit_verify_empty_chain_returns_valid_true() -> None:
    """空链 → valid=True + record_count=0（与"链被篡改"区分开）。"""
    with _setup(_admin()) as client:
        resp = client.post("/api/audit/verify?trace_id=empty-trace")
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["record_count"] == 0
        assert body["broken_seq"] is None


def test_audit_export_filters_sensitive_fields() -> None:
    """export 端点 S9：payload 中的 api_key / authorization / password 必须被 ***REDACTED*** 替换。

    写一条 trace 含三类敏感字段，export 后逐行检查不含原文。
    """
    sink = SqliteAuditSink(":memory:")
    _seed_one_trace(sink)
    app = create_app()
    app.dependency_overrides[get_audit] = lambda: sink
    app.dependency_overrides[require_proxy_identity] = lambda: _admin()
    with TestClient(app) as client:
        resp = client.get("/api/audit/traces/t1/export")
        assert resp.status_code == 200
        body = resp.text
        # 敏感字段值不能出现
        assert "sk-test-SHOULD-NOT-APPEAR" not in body
        assert "Bearer SHOULD-NOT-APPEAR" not in body
        assert "secret123-SHOULD-NOT-APPEAR" not in body
        # REDACTED 标记必须出现
        assert "***REDACTED***" in body
        # user_intent 不在敏感名单 → 原文保留
        assert "查看磁盘占用" in body
        # 末尾 verify_chain meta 行存在
        lines = [ln for ln in body.split("\n") if ln.strip()]
        assert len(lines) == 2  # 1 record + 1 meta
        meta = json.loads(lines[-1])
        assert meta["_meta"] == "verify_chain"
        assert meta["trace_id"] == "t1"
        assert meta["valid"] is True