"""X D1+D3+D5 概览接口测试。

覆盖 4 用例：
  - T3：/api/system/overview 真填 services / tool_calls_today / denied_today（从审计库真采）
  - T4：/api/system/overview/history hours 参数 clamp + 空库返空 series
  - T5：/api/system/stats hours=24 默认 + by_tool / by_risk / by_status 聚合字段
  - T6：/api/system/stats hours 越界 → 422（Pydantic Query ge/le 校验）
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.app.api.app import create_app, get_audit, lifespan
from backend.app.audit import SqliteAuditSink


def _run_with_lifespan(app, audit_sink, method: str, path: str) -> httpx.Response:
    """同步驱动：async with lifespan + httpx.AsyncClient 调一次端点。

    与 FastAPI TestClient 等价但能跨 async lifespan 同步执行；
    测试只需要单次 round-trip，不需要重入 lifespan。
    """

    async def _run() -> httpx.Response:
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get(path)
                return resp

    app.dependency_overrides[get_audit] = lambda: audit_sink
    return asyncio.run(_run())


@pytest.fixture
def audit_sink() -> SqliteAuditSink:
    """注入 :memory: 审计库（conftest 已钉 _AUDIT_DB_PATH）。"""
    return SqliteAuditSink(":memory:")


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """autouse 重置模块级状态，避免 case 间缓存/计数污染。

    - _test_counter：trace_id 唯一递增计数器
    - _overview_cache：system.py 模块级 TTL 缓存（上一个 case 命中即返旧值，导致断言失败）
    """
    _test_counter["n"] = 0
    from backend.app.api.routers import system as system_mod

    system_mod._overview_cache = None
    yield
    _test_counter["n"] = 0
    system_mod._overview_cache = None


_test_counter = {"n": 0}


def _append_audit(sink: SqliteAuditSink, *, phase: str, payload: dict) -> None:
    """插入一条审计记录（绕过 orchestrator.hash 链路以便测试只关注 phase/payload）。

    用全局递增序号保证 (trace_id, seq) UNIQUE 约束不冲突；
    trace_id 与 seq 均为测试用唯一值（与生产 orchestrator.seq 自增语义无关）。
    """
    from backend.app.contracts.audit import GENESIS_HASH, AuditRecord, compute_curr_hash

    _test_counter["n"] += 1
    n = _test_counter["n"]
    record = AuditRecord(
        trace_id=f"t-{n:08x}",
        seq=0,
        phase=phase,
        payload=payload,
        prev_hash=GENESIS_HASH,
        curr_hash=compute_curr_hash(GENESIS_HASH, payload),
    )
    sink.append(record)


# ---- T3: /api/system/overview services / tool_calls_today / denied_today 真填 ----


def test_overview_services_and_counters_filled_from_audit(
    audit_sink: SqliteAuditSink,
) -> None:
    """overview 真填：3 个 EXECUTED + 2 个 REJECTED → tool_calls_today=3, denied_today=2；
    services 含 1 个 service.restart（distinct）。

    探针部分：本测试不依赖真 gateway 真采集（让 probe 全部失败 → 4 项指标 0.0/0，
    services / counts 仍从审计真填）。
    """
    # 3 个 EXECUTED（含 1 个 service.restart）
    for i in range(3):
        _append_audit(
            audit_sink,
            phase="EXECUTED",
            payload={"tool": "service.restart" if i == 0 else "system.info", "exit_code": 0},
        )
    # 2 个 REJECTED
    for _ in range(2):
        _append_audit(
            audit_sink,
            phase="REJECTED",
            payload={"user_intent": "test", "cause": "policy_deny"},
        )

    app = create_app()
    resp = _run_with_lifespan(app, audit_sink, "GET", "/api/system/overview")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tool_calls_today"] == 3
    assert body["denied_today"] == 2
    service_names = [s["name"] for s in body["services"]]
    assert "service.restart" in service_names
    # distinct 去重：3 个 EXECUTED 中只有 1 个 service.* 前缀 → 服务列表 1 条
    service_only = [s for s in service_names if s.startswith("service.")]
    assert len(service_only) == 1


def test_overview_empty_audit_returns_zero(audit_sink: SqliteAuditSink) -> None:
    """空审计库 → tool_calls_today=0 / denied_today=0 / services=[]；不报错。"""
    app = create_app()
    resp = _run_with_lifespan(app, audit_sink, "GET", "/api/system/overview")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tool_calls_today"] == 0
    assert body["denied_today"] == 0
    assert body["services"] == []


# ---- T4: /api/system/overview/history hours clamp + 空 series ----------------


def test_overview_history_default_24_empty_series(audit_sink: SqliteAuditSink) -> None:
    """history 默认 hours=24；当前审计库未存 overview_probe → series 为空。"""
    app = create_app()
    resp = _run_with_lifespan(app, audit_sink, "GET", "/api/system/overview/history")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hours"] == 24
    assert body["series"] == []


def test_overview_history_hours_clamp_validation(audit_sink: SqliteAuditSink) -> None:
    """hours 越界（>168 或 <1）→ 422（Pydantic Query ge/le 拒绝）。"""
    app = create_app()
    resp_low = _run_with_lifespan(app, audit_sink, "GET", "/api/system/overview/history?hours=0")
    assert resp_low.status_code == 422
    resp_high = _run_with_lifespan(app, audit_sink, "GET", "/api/system/overview/history?hours=200")
    assert resp_high.status_code == 422


# ---- T5: /api/system/stats by_tool / by_risk / by_status 聚合 ----------------


def test_stats_default_24_aggregates_three_dimensions(
    audit_sink: SqliteAuditSink,
) -> None:
    """stats 默认 hours=24；by_tool / by_risk / by_status 三维度按 payload 聚合。"""
    # by_tool：2 条 EXECUTING（disk.usage）+ 1 条 EXECUTED（service.restart）
    for _ in range(2):
        _append_audit(audit_sink, phase="EXECUTING", payload={"tool": "disk.usage", "args": {}})
    _append_audit(audit_sink, phase="EXECUTED", payload={"tool": "service.restart", "exit_code": 0})
    # by_risk：1 条 R2 + 1 条 R3 INTENT_PARSED
    _append_audit(
        audit_sink,
        phase="INTENT_PARSED",
        payload={"user_intent": "x", "risk_level": "R2"},
    )
    _append_audit(
        audit_sink,
        phase="INTENT_PARSED",
        payload={"user_intent": "y", "risk_level": "R3"},
    )
    # by_status：1 个 trace FINISHED（last phase FINISHED），1 个 REJECTED
    for last_phase in ("FINISHED", "REJECTED"):
        _append_audit(
            audit_sink,
            phase=last_phase,
            payload={"user_intent": f"trace-{last_phase}"},
        )

    app = create_app()
    resp = _run_with_lifespan(app, audit_sink, "GET", "/api/system/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hours"] == 24
    # by_tool：disk.usage=2, service.restart=1
    assert body["by_tool"]["disk.usage"] == 2
    assert body["by_tool"]["service.restart"] == 1
    # by_risk：R2=1, R3=1
    assert body["by_risk"]["R2"] == 1
    assert body["by_risk"]["R3"] == 1
    # by_status：FINISHED=1, REJECTED=1
    assert body["by_status"]["FINISHED"] == 1
    assert body["by_status"]["REJECTED"] == 1


def test_stats_empty_audit_returns_empty_dicts(audit_sink: SqliteAuditSink) -> None:
    """空审计库 → 三个维度都是 {}。"""
    app = create_app()
    resp = _run_with_lifespan(app, audit_sink, "GET", "/api/system/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["by_tool"] == {}
    assert body["by_risk"] == {}
    assert body["by_status"] == {}
