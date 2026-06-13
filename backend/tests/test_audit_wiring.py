"""任务甲 — 审计落库切真验证（FakeAudit → SqliteAuditSink lifespan 单例）。

覆盖：
1. 端到端真链：注入 SqliteAuditSink(":memory:") 单例，跑一条 chat 到 FINISHED，
   verify_chain(trace_id).valid is True 且 record_count == 该 trace 落库条数。
2. 真篡改贯通：改中间一条 payload → verify_chain valid False 且 broken_seq 命中。
3. provider 单例性：lifespan 内两次 get_audit() 返回同一实例；shutdown 后连接被 close。
4. 审批续跑链连续：confirm → resume(approved) 全程无 IntegrityError、seq 连续、verify valid。

注：真实落库 sink 是单例（持 DB 句柄 + 链状态）；本套件用 :memory: 单例覆盖默认文件 sink。
"""

from __future__ import annotations

import asyncio
import sqlite3

import httpx
import pytest

from backend.app.api import app as app_module
from backend.app.api._fakes import FakeExecutor
from backend.app.api.app import create_app, get_audit, get_gateway, lifespan
from backend.app.audit import SqliteAuditSink
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _wait_state(registry, trace_id: str, target: str, timeout: float = 5.0) -> None:  # noqa: ANN001
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        session = registry.get(trace_id)
        if session is not None and session.orchestrator.state.value == target:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timeout waiting for state {target}")


class _ConfirmPolicy:
    """裁决 confirm 的 fake 策略（驱动 WAIT_APPROVAL 链路）。"""

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return PolicyVerdict(
            decision="confirm",
            final_risk="R3",
            matched_rules=["fake:confirm"],
            reason="needs approval",
            approval_required=True,
            approval_role="admin",
        )


def _confirm_gateway() -> MCPGateway:
    from backend.app.contracts.tool import ToolSpec

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="system.info",
            description="获取系统基本信息",
            risk="R0",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            requires_roles=["operator"],
            reversible=True,
        )
    )
    return MCPGateway(registry, _ConfirmPolicy(), FakeExecutor())  # type: ignore[arg-type]


# ---- 1. 端到端真链 --------------------------------------------------------


def test_chat_produces_verifiable_audit_chain() -> None:
    """跑一条 chat → FINISHED，同一 :memory: 单例 verify_chain valid + record_count 真实。"""

    async def scenario() -> None:
        sink = SqliteAuditSink(":memory:")
        app = create_app()
        app.dependency_overrides[get_audit] = lambda: sink
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                trace_id = (await client.post("/api/chat", json={"message": "看系统"})).json()[
                    "trace_id"
                ]
                await _wait_state(registry, trace_id, "FINISHED")

                result = sink.verify_chain(trace_id)
                assert result.valid is True
                rows = sink._conn.execute(
                    "SELECT COUNT(*) AS c FROM audit_records WHERE trace_id = ?", (trace_id,)
                ).fetchone()["c"]
                assert result.record_count == rows
                assert result.record_count > 0
        app.dependency_overrides.clear()

    asyncio.run(scenario())


# ---- 2. 真篡改贯通 --------------------------------------------------------


def test_tampering_detected_via_verify_chain() -> None:
    """落库后用 raw SQL 改中间一条 payload → verify_chain valid False + broken_seq 命中。"""

    async def scenario() -> None:
        sink = SqliteAuditSink(":memory:")
        app = create_app()
        app.dependency_overrides[get_audit] = lambda: sink
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                trace_id = (await client.post("/api/chat", json={"message": "看系统"})).json()[
                    "trace_id"
                ]
                await _wait_state(registry, trace_id, "FINISHED")
                assert sink.verify_chain(trace_id).valid is True

                # 篡改中间一条记录的 payload（seq=1）
                sink._conn.execute(
                    "UPDATE audit_records SET payload = ? WHERE trace_id = ? AND seq = ?",
                    ('{"tampered": true}', trace_id, 1),
                )
                sink._conn.commit()

                result = sink.verify_chain(trace_id)
                assert result.valid is False
                assert result.broken_seq == 1
        app.dependency_overrides.clear()

    asyncio.run(scenario())


# ---- 3. provider 单例性 + close ------------------------------------------


def test_audit_provider_is_singleton_and_closed_on_shutdown(monkeypatch) -> None:  # noqa: ANN001
    """lifespan 内两次 get_audit() 同一实例；shutdown 后底层连接被 close。"""
    # 用 :memory: 避免测试落地文件
    monkeypatch.setattr(app_module, "_AUDIT_DB_PATH", ":memory:")

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            a1 = app_module.get_audit()
            a2 = app_module.get_audit()
            assert a1 is a2  # 单例
            captured = a1
        # shutdown 后连接已关闭：再操作抛 ProgrammingError
        with pytest.raises(sqlite3.ProgrammingError):
            captured._conn.execute("SELECT 1")  # type: ignore[attr-defined]

    asyncio.run(scenario())


# ---- 4. 审批续跑链连续 ----------------------------------------------------


def test_approval_resume_chain_continuous_no_replay() -> None:
    """confirm → resume(approved) 全程无 IntegrityError、seq 自 0 连续、verify_chain valid。"""

    async def scenario() -> None:
        sink = SqliteAuditSink(":memory:")
        app = create_app()
        app.dependency_overrides[get_audit] = lambda: sink
        app.dependency_overrides[get_gateway] = _confirm_gateway
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                trace_id = (await client.post("/api/chat", json={"message": "重启服务"})).json()[
                    "trace_id"
                ]
                await _wait_state(registry, trace_id, "WAIT_APPROVAL")

                rr = await client.post(
                    "/api/approvals/resume",
                    headers={"X-User-Role": "admin"},
                    json={"trace_id": trace_id, "approved": True},
                )
                assert rr.status_code == 200
                await _wait_state(registry, trace_id, "FINISHED")

                # 链连续可复算（verify_chain 内含 seq 自 0 连续 + 逐条复算）
                result = sink.verify_chain(trace_id)
                assert result.valid is True
                seqs = [
                    row["seq"]
                    for row in sink._conn.execute(
                        "SELECT seq FROM audit_records WHERE trace_id = ? ORDER BY seq ASC",
                        (trace_id,),
                    ).fetchall()
                ]
                assert seqs == list(range(len(seqs)))  # 自 0 连续无重放
        app.dependency_overrides.clear()

    asyncio.run(scenario())
