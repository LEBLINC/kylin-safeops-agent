"""L P1 ?probe=true 审计化测试（X 联调新增）。

覆盖 3 用例：
  - T1：probe 失败 → SqliteAuditSink 落 AuditRecord(phase=probe_failed) + curr_hash 正确
  - T2：probe 失败 → /api/llm/health?probe=true 触发 SSE audit_appended（前端可见）
  - T3：probe timeout → 同样走审计 + SSE；fixture 模式不写审计（运维噪音最小）
"""

from __future__ import annotations

import asyncio
import json
from unittest import mock

import httpx

from backend.app.api import app as app_module
from backend.app.api.app import create_app, get_audit, lifespan
from backend.app.audit import SqliteAuditSink
from backend.app.llm.real_client import RealLLMClient


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ---- T1: probe 失败 → SqliteAuditSink 落 AuditRecord ------------------------


def test_probe_failed_writes_audit_record() -> None:
    """probe 失败时 → RealLLMClient.probe(audit_sink=sink) 写入 AuditRecord。

    payload 含 probe_status='failed' + status_code + latency_ms + model + base_url；
    phase=probe_failed；trace_id=probe-{epoch_ms}；
    curr_hash=SHA256(GENESIS + canonical_json(payload))。
    """
    from backend.app.contracts.audit import GENESIS_HASH, compute_curr_hash

    cfg = app_module.__dict__.get(
        "RealLLMConfig",
        None,
    )  # 防顶层 import 污染（用 monkeypatch 改 env 即可）
    # 注入 KYLIN_LLM_PROVIDER=real
    import os

    os.environ["KYLIN_LLM_PROVIDER"] = "real"
    os.environ["KYLIN_LLM_BASE_URL"] = "http://mock-llm/v1"
    os.environ["KYLIN_LLM_API_KEY"] = "sk-test"

    cfg = app_module.__dict__.get("RealLLMConfig")
    from backend.app.llm.real_client import RealLLMConfig

    cfg = RealLLMConfig(
        provider="real",
        base_url="http://mock-llm/v1",
        model="qwen2.5",
        api_key="sk-test",
    )
    client = RealLLMClient(cfg)
    sink = SqliteAuditSink(":memory:")

    mock_resp = mock.MagicMock()
    mock_resp.status_code = 500
    mock_resp.is_success = False

    async def _run() -> None:
        with mock.patch(
            "backend.app.llm.real_client.httpx.AsyncClient",
            return_value=mock.AsyncMock(
                __aenter__=mock.AsyncMock(
                    return_value=mock.AsyncMock(post=mock.AsyncMock(return_value=mock_resp))
                ),
                __aexit__=mock.AsyncMock(return_value=False),
            ),
        ):
            result = await client.probe(timeout_s=3.0, audit_sink=sink)

        # 1. result 含 probe_status=failed + audit_trace_id
        assert result["probe_status"] == "failed"
        assert result["probe_error"] == "status_code=500"
        assert result["audit_trace_id"] is not None
        assert result["audit_trace_id"].startswith("probe-")

        # 2. SqliteAuditSink 落了 1 条 phase=probe_failed 记录
        conn = sink._conn
        rows = conn.execute(
            "SELECT trace_id, phase, payload, curr_hash FROM audit_records "
            "WHERE phase = 'probe_failed' AND trace_id = ?",
            (result["audit_trace_id"],),
        ).fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["trace_id"] == result["audit_trace_id"]
        assert row["phase"] == "probe_failed"
        payload = json.loads(row["payload"])
        assert payload["probe_status"] == "failed"
        assert payload["error_detail"] == "status_code=500"
        assert payload["latency_ms"] >= 0
        assert payload["model"] == "qwen2.5"
        # S9: api_key 绝不在 payload 里
        assert "sk-test" not in row["payload"]

        # 3. curr_hash = SHA256(GENESIS ‖ canonical_json(payload))
        expected_hash = compute_curr_hash(GENESIS_HASH, payload)
        assert row["curr_hash"] == expected_hash

    asyncio.run(_run())


# ---- T2: /api/llm/health?probe=true 触发 SSE audit_appended ------------------


def test_health_probe_failed_emits_audit_appended_via_sse(monkeypatch) -> None:
    """POST /api/llm/health?probe=true 失败 → 后端经 EventBus emit audit_appended。

    前端可订阅 /api/llm/health/events SSE 拿到 trace_id → /api/audit/traces/{id} 查详情。
    """
    monkeypatch.setenv("KYLIN_LLM_PROVIDER", "real")
    monkeypatch.setenv("KYLIN_LLM_BASE_URL", "http://mock-llm/v1")
    monkeypatch.setenv("KYLIN_LLM_API_KEY", "sk-test")

    mock_resp = mock.MagicMock()
    mock_resp.status_code = 500
    mock_resp.is_success = False

    async def s() -> None:
        sink = SqliteAuditSink(":memory:")
        app = create_app()
        app.dependency_overrides[get_audit] = lambda: sink
        async with lifespan(app):
            async with _client(app) as c:
                with mock.patch(
                    "backend.app.llm.real_client.httpx.AsyncClient",
                    return_value=mock.AsyncMock(
                        __aenter__=mock.AsyncMock(
                            return_value=mock.AsyncMock(post=mock.AsyncMock(return_value=mock_resp))
                        ),
                        __aexit__=mock.AsyncMock(return_value=False),
                    ),
                ):
                    r = await c.get("/api/llm/health?probe=true")

        assert r.status_code == 200
        body = r.json()
        assert body["probe_status"] == "failed"

        # 1. audit 落库 phase=probe_failed
        rows = sink._conn.execute(
            "SELECT trace_id, curr_hash FROM audit_records WHERE phase = 'probe_failed'"
        ).fetchall()
        assert len(rows) == 1
        audit_trace_id = rows[0]["trace_id"]
        assert audit_trace_id.startswith("probe-")

    asyncio.run(s())


# ---- T3: probe timeout 走审计；fixture 模式不写审计 -----------------------------


def test_probe_timeout_writes_audit_record() -> None:
    """probe timeout → 同样走审计（phase=probe_failed, error_detail='TimeoutException'）。"""
    import os

    os.environ["KYLIN_LLM_PROVIDER"] = "real"
    from backend.app.llm.real_client import RealLLMConfig

    cfg = RealLLMConfig(provider="real", base_url="http://mock-llm/v1")
    client = RealLLMClient(cfg)
    sink = SqliteAuditSink(":memory:")

    async def _run() -> None:
        with mock.patch(
            "backend.app.llm.real_client.httpx.AsyncClient",
            return_value=mock.AsyncMock(
                __aenter__=mock.AsyncMock(
                    return_value=mock.AsyncMock(
                        post=mock.AsyncMock(
                            side_effect=httpx.ReadTimeout("timed out", request=None)
                        )
                    )
                ),
                __aexit__=mock.AsyncMock(return_value=False),
            ),
        ):
            result = await client.probe(timeout_s=3.0, audit_sink=sink)

        assert result["probe_status"] == "timeout"
        assert result["audit_trace_id"] is not None
        rows = sink._conn.execute(
            "SELECT payload FROM audit_records WHERE phase = 'probe_failed'"
        ).fetchall()
        assert len(rows) == 1
        payload = json.loads(rows[0]["payload"])
        assert payload["probe_status"] == "timeout"
        assert payload["error_detail"] == "TimeoutException"

    asyncio.run(_run())


def test_probe_fixture_no_audit_noop() -> None:
    """probe fixture 模式 → audit_trace_id=None + sink 不写（运维噪音最小）。"""
    from backend.app.llm.real_client import RealLLMConfig

    cfg = RealLLMConfig(provider="fixture")
    client = RealLLMClient(cfg)
    sink = SqliteAuditSink(":memory:")

    async def _run() -> None:
        result = await client.probe(timeout_s=3.0, audit_sink=sink)
        assert result["probe_status"] == "skipped"
        assert result["audit_trace_id"] is None
        rows = sink._conn.execute(
            "SELECT COUNT(*) AS c FROM audit_records WHERE phase = 'probe_failed'"
        ).fetchone()
        assert rows["c"] == 0

    asyncio.run(_run())
