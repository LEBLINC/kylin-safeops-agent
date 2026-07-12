"""X D6 /api/tools/calls/{call_id} 详情端点测试。

覆盖 2 用例：
  - T7：传入 trace_id（已有 EXECUTING/EXECUTED 记录）→ 返回完整 tool_name/args/exit_code/timestamp
  - T8：未知 call_id → 404
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.app.api.app import create_app, get_audit, lifespan
from backend.app.audit import SqliteAuditSink


@pytest.fixture
def audit_sink() -> SqliteAuditSink:
    return SqliteAuditSink(":memory:")


def _append_audit(
    sink: SqliteAuditSink,
    *,
    trace_id: str,
    seq: int,
    phase: str,
    payload: dict,
) -> None:
    """按 trace_id+seq 顺序追加审计（不复算 hash chain，单测只关注 SELECT 逻辑）。"""
    from backend.app.contracts.audit import GENESIS_HASH, AuditRecord, compute_curr_hash

    record = AuditRecord(
        trace_id=trace_id,
        seq=seq,
        phase=phase,
        payload=payload,
        prev_hash=GENESIS_HASH,
        curr_hash=compute_curr_hash(GENESIS_HASH, payload),
    )
    sink.append(record)


def _run_with_lifespan(app, audit_sink, path: str) -> httpx.Response:
    async def _run() -> httpx.Response:
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get(path)

    app.dependency_overrides[get_audit] = lambda: audit_sink
    return asyncio.run(_run())


# ---- T7: 详情返完整 ------------------------------------------------------


def test_tools_call_detail_returns_full_record(
    audit_sink: SqliteAuditSink,
) -> None:
    """call_id=trace_id 已有 EXECUTING + EXECUTED 记录 → 返回末条 EXECUTED 的工具详情。

    payload 形态：{"tool": "service.restart", "exit_code": 0}；args 留空（EXECUTED 单工具
    留痕 payload 不含 args，但 EXECUTING 含；本测试覆盖两种 phase，详情应返末条 EXECUTED）。
    """
    trace_id = "trace-abc-123"
    _append_audit(
        audit_sink,
        trace_id=trace_id,
        seq=0,
        phase="EXECUTING",
        payload={"tool": "service.restart", "args": {"service_name": "nginx.service"}},
    )
    _append_audit(
        audit_sink,
        trace_id=trace_id,
        seq=1,
        phase="EXECUTED",
        payload={"tool": "service.restart", "exit_code": 0},
    )

    app = create_app()
    resp = _run_with_lifespan(app, audit_sink, f"/api/tools/calls/{trace_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["call_id"] == trace_id
    assert body["trace_id"] == trace_id
    assert body["seq"] == 1  # 末条 EXECUTED
    assert body["tool_name"] == "service.restart"
    assert body["exit_code"] == 0
    # timestamp 应当是合理 epoch（> 2024-01-01 = 1704067200）
    assert body["timestamp"] > 1_704_067_200


def test_tools_call_detail_s9_redacts_sensitive_args(
    audit_sink: SqliteAuditSink,
) -> None:
    """S9 守门：payload.args 含 api_key / bind_password / secret → 详情返 ***REDACTED***。

    只有 EXECUTING（无 EXECUTED 跟随）→ 末条 = EXECUTING → 过滤生效。
    api_key / bind_password / secret 值不能在响应里出现（防凭据泄漏）。
    """
    trace_id = "trace-secret-456"
    _append_audit(
        audit_sink,
        trace_id=trace_id,
        seq=0,
        phase="EXECUTING",
        payload={
            "tool": "service.restart",
            "args": {
                "service_name": "nginx.service",
                "api_key": "AKIA-VERY-SECRET",
                "bind_password": "pass-123",
                "secret": "shh",
            },
        },
    )

    app = create_app()
    resp = _run_with_lifespan(app, audit_sink, f"/api/tools/calls/{trace_id}")
    assert resp.status_code == 200
    body = resp.json()
    args = body["args"]
    # service_name 不在黑名单，原样返
    assert args.get("service_name") == "nginx.service"
    # 3 类敏感字段值全被 REDACTED
    assert args.get("api_key") == "***REDACTED***"
    assert args.get("bind_password") == "***REDACTED***"
    assert args.get("secret") == "***REDACTED***"
    # 明文绝不出现
    raw = resp.text
    assert "AKIA-VERY-SECRET" not in raw
    assert "pass-123" not in raw
    assert "shh" not in raw


# ---- T8: 未知 call_id → 404 ----------------------------------------------


def test_tools_call_detail_unknown_returns_404(audit_sink: SqliteAuditSink) -> None:
    """未知 trace_id → 404（与 audit/traces/{trace_id} 行为对齐）。"""
    app = create_app()
    resp = _run_with_lifespan(app, audit_sink, "/api/tools/calls/nonexistent-trace-id")
    assert resp.status_code == 404
    assert "nonexistent-trace-id" in resp.text


def test_tools_call_detail_trace_without_executed_returns_404(
    audit_sink: SqliteAuditSink,
) -> None:
    """trace 存在但只有非 EXECUTING/EXECUTED 阶段（如 RECEIVED）→ 404。"""
    trace_id = "trace-only-received"
    _append_audit(
        audit_sink,
        trace_id=trace_id,
        seq=0,
        phase="RECEIVED",
        payload={"user_intent": "test"},
    )

    app = create_app()
    resp = _run_with_lifespan(app, audit_sink, f"/api/tools/calls/{trace_id}")
    assert resp.status_code == 404
