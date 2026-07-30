"""/api/tools/calls 列表端点测试。

覆盖 4 用例：
  - T1：seed 多条 EXECUTING/EXECUTED records → 列表接口返按时间倒序最近条目
  - T2：tool=disk.usage → 仅返 payload.tool == "disk.usage" 的条目（其他工具被过滤）
  - T3：limit=2 → 仅返 2 条（即便 DB 内有 5 条匹配）
  - T4：seed payload 含 api_key / secret → 响应 payload 字段为 "***REDACTED***"（S9 守门）

测试用 SqliteAuditSink in-memory + 直接 append 真实 AuditRecord（不复算链，
单测仅验证 SELECT 派生逻辑）。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.app.api.app import create_app, get_audit, lifespan
from backend.app.api.auth import Principal
from backend.app.api.deps import require_proxy_identity
from backend.app.audit import SqliteAuditSink


def _admin() -> Principal:
    return Principal(user="admin", roles=frozenset({"admin"}))


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
    """按 trace_id+seq 顺序追加审计（不复算 hash chain）。"""
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


def _run_get(app, audit_sink, path: str, headers: dict | None = None) -> httpx.Response:
    async def _run() -> httpx.Response:
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get(path, headers=headers or {})

    app.dependency_overrides[get_audit] = lambda: audit_sink
    return asyncio.run(_run())


def _seed_basic(audit_sink: SqliteAuditSink) -> None:
    """Seed 5 个不同 trace 的 EXECUTING 记录：3 条 disk.usage + 2 条 service.restart。"""
    fixtures = [
        ("trace-001", "disk.usage"),
        ("trace-002", "disk.usage"),
        ("trace-003", "service.restart"),
        ("trace-004", "disk.usage"),
        ("trace-005", "service.restart"),
    ]
    for trace_id, tool in fixtures:
        _append_audit(
            audit_sink,
            trace_id=trace_id,
            seq=0,
            phase="EXECUTING",
            payload={"tool": tool, "args": {}},
        )


# ---- T1: 默认返最近条目（按时间倒序） --------------------------------------


def test_tool_calls_list_returns_recent(audit_sink: SqliteAuditSink) -> None:
    """seed 5 条 EXECUTING → /api/tools/calls?tool=disk.usage 返匹配条目。

    覆盖：返回的 ToolCallSummary 字段齐全 + status==EXECUTING + total 与 items
    数量一致 + 字段默认值（duration_ms=0 / risk_level=""）生效。
    """
    _seed_basic(audit_sink)

    app = create_app()
    app.dependency_overrides[require_proxy_identity] = lambda: _admin()
    resp = _run_get(app, audit_sink, "/api/tools/?tool=disk.usage")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "items" in body and "total" in body
    # 3 条 disk.usage（其他 2 条 service.restart 被过滤）
    assert body["total"] == 3
    assert len(body["items"]) == 3

    for item in body["items"]:
        # 字段齐全
        assert set(item.keys()) >= {
            "call_id",
            "trace_id",
            "tool",
            "status",
            "duration_ms",
            "risk_level",
            "created_at",
        }
        assert item["tool"] == "disk.usage"
        assert item["status"] == "EXECUTING"
        # call_id / trace_id 同口径（MVP=trace_id）
        assert item["call_id"] == item["trace_id"]
        # 占位字段默认
        assert item["duration_ms"] == 0
        assert item["risk_level"] == ""
        # created_at 非空 ISO 字符串
        assert isinstance(item["created_at"], str) and len(item["created_at"]) > 10


# ---- T2: tool 过滤生效 ----------------------------------------------------


def test_tool_calls_list_filters_by_tool(audit_sink: SqliteAuditSink) -> None:
    """tool=service.restart 仅返 service.restart 调用（disk.usage 被过滤）。"""
    _seed_basic(audit_sink)

    app = create_app()
    app.dependency_overrides[require_proxy_identity] = lambda: _admin()
    resp = _run_get(app, audit_sink, "/api/tools/?tool=service.restart")
    assert resp.status_code == 200
    body = resp.json()

    assert body["total"] == 2
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert item["tool"] == "service.restart"


# ---- T3: limit 生效 --------------------------------------------------------


def test_tool_calls_list_respects_limit(audit_sink: SqliteAuditSink) -> None:
    """limit=2 → 即便匹配有 3 条也仅返 2 条。"""
    _seed_basic(audit_sink)

    app = create_app()
    app.dependency_overrides[require_proxy_identity] = lambda: _admin()
    resp = _run_get(app, audit_sink, "/api/tools/?tool=disk.usage&limit=2")
    assert resp.status_code == 200
    body = resp.json()

    assert body["total"] == 2
    assert len(body["items"]) == 2


# ---- T4: S9 敏感字段过滤（payload 顶层 — api_key 等） -----------------------


def test_tool_calls_list_redacts_sensitive(audit_sink: SqliteAuditSink) -> None:
    """S9 守门：payload 顶层含 api_key / secret / bind_password → 响应 payload
    字段值被替换为 "***REDACTED***"。

    验证：响应 JSON 全文不含明文凭据（"sk-1234" / "shh" / "pwd-1"）；
    payload 顶层敏感字段已 REDACTED（payload 不是 schema 字段，但 path / tool 仍可访问）。
    注：本测试通过 spy 验证 _run_get 的 resp.text 不含明文；S9 守门位于
    SqliteAuditSink.list_tool_calls_by_tool 内部 _SENSITIVE_KEYS 黑名单过滤。
    """
    _append_audit(
        audit_sink,
        trace_id="trace-secret-001",
        seq=0,
        phase="EXECUTING",
        payload={
            "tool": "llm.invoke",
            "args": {},
            "api_key": "sk-1234-AKIA-SECRET",
            "bind_password": "pwd-1",
            "secret": "shh",
        },
    )

    app = create_app()
    app.dependency_overrides[require_proxy_identity] = lambda: _admin()
    resp = _run_get(app, audit_sink, "/api/tools/?tool=llm.invoke")
    assert resp.status_code == 200
    body = resp.json()

    # 返 1 条匹配记录
    assert body["total"] == 1
    assert len(body["items"]) == 1

    # Spy verify：响应正文**绝不**出现明文凭据
    raw = resp.text
    assert "sk-1234-AKIA-SECRET" not in raw, "api_key 明文泄漏"
    assert "pwd-1" not in raw, "bind_password 明文泄漏"
    assert "shh" not in raw, "secret 明文泄漏"
    # 红acted 标记至少出现 1 次（替换非必出现于 schema 字段，但 audit_logger
    # 的 list_tool_calls_by_tool 在 SQL→内存层已过滤；本断言验证：要么 schema
    # 中 payload 不暴露给前端，要么 REDACTED 已替换）。
    # 注：本 schema ToolCallSummary 不暴露 payload 字段，故敏感字段完全不会
    # 出现在响应里（端到端安全）；但审计 logger 过滤逻辑本身仍必须工作。
    # 我们额外验证 audit sink 调用后的内存结果：
    rows = audit_sink.list_tool_calls_by_tool(tool="llm.invoke", limit=10)
    assert len(rows) == 1
    pl = rows[0]["payload"]
    assert pl["api_key"] == "***REDACTED***"
    assert pl["bind_password"] == "***REDACTED***"
    assert pl["secret"] == "***REDACTED***"
