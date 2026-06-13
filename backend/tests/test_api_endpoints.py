"""api 层增量2–6 端到端测试（httpx ASGITransport，不联网、不跑真命令）。

覆盖：
- 增量2: POST /api/chat → trace_id → SSE 收到事件流到 done。
- 增量3: confirm → SSE await_approval → resume(True) → 续收 executing/tool_result/verified。
- 增量4: tools/registry 字段名为 tool；tools/call 走通；未注册被拦。
- 增量5: 会话 create/list；system/overview 桩数据。
- 增量6: rca/analyze 返回 trace_id；rca/{trace_id} 返回 report。

lifespan 手动进入以初始化全局单例（ASGITransport 不触发 lifespan）。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from backend.app.api import app as app_module
from backend.app.api._fakes import FakeExecutor
from backend.app.api.app import create_app, get_audit, get_gateway, lifespan
from backend.app.api.routers import system as system_router
from backend.app.audit import SqliteAuditSink
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


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
    registry = ToolRegistry()
    from backend.app.contracts.tool import ToolSpec

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


# ---- 增量2 ---------------------------------------------------------------


def test_chat_post_then_sse_to_done() -> None:
    """POST /api/chat 拿 trace_id，SSE 收到 intent_parsed..verified 直到 done。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                resp = await client.post("/api/chat", json={"message": "看下系统"})
                assert resp.status_code == 200
                data = resp.json()
                trace_id = data["trace_id"]
                assert data["stream_url"] == f"/api/chat/{trace_id}/events"

                lines: list[str] = []
                async with client.stream("GET", data["stream_url"]) as r:
                    async for line in r.aiter_lines():
                        lines.append(line)
                        if "event: done" in line:
                            break
                body = "\n".join(lines)
                assert "intent_parsed" in body
                assert "verified" in body
                assert "event: done" in body

    asyncio.run(scenario())


# ---- 增量3 ---------------------------------------------------------------


def test_approval_resume_continues_same_sse() -> None:
    """confirm → await_approval(同一队列) → resume(True) → 续推 executing/tool_result/verified。

    注：httpx ASGITransport 会缓冲未完成的流式响应（confirm 流在 resume 前不结束），
    故此处直接消费同一 trace_id 的事件队列验证"事件续推同一 SSE 队列"的机制，
    并真实打 POST /api/approvals/resume 端点（含 404/409 守卫见独立用例）。
    """

    async def _wait_state(registry, trace_id: str, target: str, timeout: float = 5.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            session = registry.get(trace_id)
            if session is not None and session.orchestrator.state.value == target:
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"timeout waiting for state {target}")

    def _drain_types(queue) -> list[str]:  # noqa: ANN001
        out: list[str] = []
        while not queue.empty():
            ev = queue.get_nowait()
            if ev is not None:
                out.append(ev.type)
        return out

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _confirm_gateway
        async with lifespan(app):
            bus = app_module.get_bus()
            registry = app_module.get_registry()
            async with _client(app) as client:
                resp = await client.post("/api/chat", json={"message": "重启服务"})
                trace_id = resp.json()["trace_id"]

                # 后台 run 推进到 WAIT_APPROVAL（暂停，保活等 resume）
                await _wait_state(registry, trace_id, "WAIT_APPROVAL")
                queue = bus.get(trace_id)
                assert queue is not None
                before = _drain_types(queue)
                assert "await_approval" in before

                # 打审批端点续跑
                rr = await client.post(
                    "/api/approvals/resume",
                    headers={"X-User-Role": "admin"},
                    json={"trace_id": trace_id, "approved": True},
                )
                assert rr.status_code == 200
                assert rr.json()["accepted"] is True

                # 续跑到终态，事件进入同一队列
                await _wait_state(registry, trace_id, "FINISHED")
                after = _drain_types(queue)
                assert "executing" in after
                assert "tool_result" in after
                assert "verified" in after
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_resume_unknown_trace_404() -> None:
    """resume 未知 trace_id → 404。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                rr = await client.post(
                    "/api/approvals/resume",
                    json={"trace_id": "nope", "approved": True},
                )
                assert rr.status_code == 404

    asyncio.run(scenario())


def test_concurrent_resume_only_one_succeeds() -> None:
    """L-4：并发两个 resume 只有一个被受理(200)，另一个 409（per-trace 重入保护）。"""

    async def _wait_state(registry, trace_id: str, target: str, timeout: float = 5.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            session = registry.get(trace_id)
            if session is not None and session.orchestrator.state.value == target:
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"timeout waiting for {target}")

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _confirm_gateway
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                trace_id = (await client.post("/api/chat", json={"message": "重启"})).json()[
                    "trace_id"
                ]
                await _wait_state(registry, trace_id, "WAIT_APPROVAL")

                r1, r2 = await asyncio.gather(
                    client.post(
                        "/api/approvals/resume",
                        headers={"X-User-Role": "admin"},
                        json={"trace_id": trace_id, "approved": True},
                    ),
                    client.post(
                        "/api/approvals/resume",
                        headers={"X-User-Role": "admin"},
                        json={"trace_id": trace_id, "approved": True},
                    ),
                )
                statuses = sorted([r1.status_code, r2.status_code])
                assert statuses == [200, 409]  # 恰一个受理、一个被拒
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_resume_non_wait_approval_409() -> None:
    """resume 一个已终态(非 WAIT_APPROVAL)的 trace → 409（approvals.py 守卫，L-3 补测）。

    默认真策略下 fake LLM 提议 system.info(R0)→allow→run 直达 FINISHED；
    对已 FINISHED 的 trace 再打 resume → 409。
    """

    async def _wait_terminal(registry, trace_id: str, timeout: float = 5.0) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            session = registry.get(trace_id)
            if session is not None and session.orchestrator.state.value in ("FINISHED", "REJECTED"):
                return session.orchestrator.state.value
            await asyncio.sleep(0.01)
        raise AssertionError("timeout waiting for terminal state")

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                trace_id = (await client.post("/api/chat", json={"message": "看系统"})).json()[
                    "trace_id"
                ]
                await _wait_terminal(registry, trace_id)
                rr = await client.post(
                    "/api/approvals/resume",
                    json={"trace_id": trace_id, "approved": True},
                )
                assert rr.status_code == 409
                assert "approval" in rr.json()["detail"].lower()

    asyncio.run(scenario())


# ---- 增量4 ---------------------------------------------------------------


def test_tools_registry_field_is_tool() -> None:
    """registry 输出键名是 tool（非 name），且为真 os_ops 工具集。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                resp = await client.get("/api/tools/registry")
                assert resp.status_code == 200
                items = resp.json()
                assert len(items) >= 1
                assert "tool" in items[0]
                assert "name" not in items[0]
                names = {it["tool"] for it in items}
                # 切真后注册的是真 os_ops 工具集
                assert "system.info" in names
                assert "disk.usage" in names

    asyncio.run(scenario())


def test_tools_call_executes_and_unregistered_blocked() -> None:
    """call 真只读工具(system.info)→真策略 allow→executed True；未注册→deny→executed False。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                ok = await client.post(
                    "/api/tools/call",
                    json={"tool": "system.info", "args": {}},
                )
                assert ok.status_code == 200
                assert ok.json()["executed"] is True

                bad = await client.post(
                    "/api/tools/call",
                    json={"tool": "ghost.tool", "args": {}},
                )
                assert bad.status_code == 200
                # 未注册工具被只读门兜住（保守视为非只读），executed=False
                assert bad.json()["executed"] is False

    asyncio.run(scenario())


def test_tools_call_real_policy_deny_via_api() -> None:
    """真策略经 B/S 层实质生效：只读工具承载触发 deny 的路径参数 → executed False、verdict=deny。

    log.large_log_scan(R1 只读，过只读门) + path=/etc/shadow → 真策略 FILE001 deny。
    证明策略闸经 API 真实拦截（非 allow-all 桩）。
    """

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                resp = await client.post(
                    "/api/tools/call",
                    json={"tool": "log.large_log_scan", "args": {"path": "/etc/shadow"}},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["executed"] is False
                assert data["verdict"] is not None
                assert data["verdict"]["decision"] == "deny"

    asyncio.run(scenario())


def _change_tool_gateway() -> MCPGateway:
    """注册一个 R3 变更工具 + allow-all 策略：用于验证只读门（防御纵深）。"""
    from backend.app.api._fakes import FakePolicyEngine
    from backend.app.contracts.tool import ToolSpec

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="service.restart",
            description="重启服务（变更动作）",
            risk="R3",
            input_schema={
                "type": "object",
                "properties": {"service_name": {"type": "string"}},
                "required": ["service_name"],
            },
            requires_roles=["admin"],
            reversible=False,
        )
    )
    # 注意：策略故意 allow-all，证明只读门不依赖策略正确性
    return MCPGateway(registry, FakePolicyEngine(), FakeExecutor())  # type: ignore[arg-type]


def test_tools_call_change_tool_blocked_by_readonly_gate() -> None:
    """S6 防御纵深：变更工具(R2+)经 /api/tools/call 被只读门拦下，executed=False。

    即便策略 allow-all（误配模拟），手动端点也绝不执行变更工具——
    变更动作必须走 chat→审批链路。
    """

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _change_tool_gateway
        async with lifespan(app):
            async with _client(app) as client:
                resp = await client.post(
                    "/api/tools/call",
                    json={"tool": "service.restart", "args": {"service_name": "nginx.service"}},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["executed"] is False
                assert "read-only" in data["reason"]
        app.dependency_overrides.clear()

    asyncio.run(scenario())


# ---- 增量5 ---------------------------------------------------------------


def test_sessions_create_and_list() -> None:
    """会话 create → list 能查到。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                created = await client.post("/api/chat/sessions", json={"title": "排障会话"})
                assert created.status_code == 200
                sid = created.json()["session_id"]
                assert created.json()["title"] == "排障会话"

                listed = await client.get("/api/chat/sessions")
                assert listed.status_code == 200
                ids = [s["session_id"] for s in listed.json()]
                assert sid in ids

    asyncio.run(scenario())


def test_sessions_get_patch_delete() -> None:
    """单个 GET / PATCH 改名 / DELETE，含 404 守卫。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                sid = (await client.post("/api/chat/sessions", json={"title": "原标题"})).json()[
                    "session_id"
                ]

                # 单个 GET
                got = await client.get(f"/api/chat/sessions/{sid}")
                assert got.status_code == 200
                assert got.json()["title"] == "原标题"

                # PATCH 改名
                patched = await client.patch(f"/api/chat/sessions/{sid}", json={"title": "新标题"})
                assert patched.status_code == 200
                assert patched.json()["title"] == "新标题"

                # DELETE
                deleted = await client.delete(f"/api/chat/sessions/{sid}")
                assert deleted.status_code == 200
                assert deleted.json() == {"session_id": sid, "deleted": True}

                # 删后再取 → 404
                assert (await client.get(f"/api/chat/sessions/{sid}")).status_code == 404

    asyncio.run(scenario())


def test_sessions_404_guards() -> None:
    """未知 session_id 的 GET/PATCH/DELETE 均 404。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                assert (await client.get("/api/chat/sessions/nope")).status_code == 404
                p = await client.patch("/api/chat/sessions/nope", json={"title": "x"})
                assert p.status_code == 404
                assert (await client.delete("/api/chat/sessions/nope")).status_code == 404

    asyncio.run(scenario())


def test_session_update_rejects_empty_title() -> None:
    """PATCH 空标题被 schema 拒（min_length=1 → 422）。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                sid = (await client.post("/api/chat/sessions", json={})).json()["session_id"]
                r = await client.patch(f"/api/chat/sessions/{sid}", json={"title": ""})
                assert r.status_code == 422

    asyncio.run(scenario())


def test_system_overview_flat_fields() -> None:
    """system/overview 返回扁平指标 + services 列表 + 任务D 来源标注与管道连通证据。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                resp = await client.get("/api/system/overview")
                assert resp.status_code == 200
                data = resp.json()
                for key in (
                    "cpu_usage",
                    "memory_usage",
                    "root_disk_usage",
                    "zombie_processes",
                    "tool_calls_today",
                    "denied_today",
                    "services",
                ):
                    assert key in data
                assert isinstance(data["services"], list)
                # 任务D：来源态显式标注（桩执行器下绝不冒充真实数据）
                assert data["data_source"] == "stub_executor"
                # 任务D：采集管道真实经 gateway dispatch 只读工具（管道连通证据）
                assert "system.info" in data["probed_tools"]
                assert "disk.usage" in data["probed_tools"]

    asyncio.run(scenario())


def test_overview_does_not_produce_audit() -> None:
    """GAP-1 方案 b：概览只读探针豁免哈希链审计——调用 overview 不新增任何审计记录。"""

    async def scenario() -> None:
        sink = SqliteAuditSink(":memory:")
        app = create_app()
        app.dependency_overrides[get_audit] = lambda: sink
        async with lifespan(app):
            async with _client(app) as client:
                resp = await client.get("/api/system/overview")
                assert resp.status_code == 200
                # 概览路径不经 orchestrator → 不落审计（有界豁免成立）
                count = sink._conn.execute("SELECT COUNT(*) AS c FROM audit_records").fetchone()[
                    "c"
                ]
                assert count == 0
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_overview_probes_only_readonly_tools() -> None:
    """概览只 dispatch 只读工具：probed_tools ⊆ 已知 R0 探针集（硬只读护栏）。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                data = (await client.get("/api/system/overview")).json()
                probed = set(data["probed_tools"])
                assert probed <= {"system.info", "disk.usage", "process.list"}

    asyncio.run(scenario())


def test_overview_skips_change_tool_defense_in_depth(monkeypatch) -> None:  # noqa: ANN001
    """硬只读护栏（方案 b 基石）：即便策略 allow-all 且探针表混入变更工具，概览也不 dispatch 它。"""
    # 把变更工具混入探针表（模拟误配），并用 allow-all 策略 gateway
    monkeypatch.setattr(system_router, "_OVERVIEW_PROBE_TOOLS", ("service.restart",))
    monkeypatch.setattr(system_router, "_overview_cache", None)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _change_tool_gateway
        async with lifespan(app):
            async with _client(app) as client:
                data = (await client.get("/api/system/overview")).json()
                # 变更工具被 is_read_only 护栏拦下，绝不出现在 probed_tools
                assert "service.restart" not in data["probed_tools"]
        app.dependency_overrides.clear()

    asyncio.run(scenario())


# ---- 增量6 ---------------------------------------------------------------


def test_rca_analyze_then_get_report() -> None:
    """rca/analyze 返回 trace_id；rca/{trace_id} 返回 report 结构。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                a = await client.post(
                    "/api/rca/analyze",
                    json={"problem_type": "disk_full", "description": "根分区满"},
                )
                assert a.status_code == 200
                trace_id = a.json()["trace_id"]

                g = await client.get(f"/api/rca/{trace_id}")
                assert g.status_code == 200
                assert g.json()["trace_id"] == trace_id
                assert "report" in g.json()

                # 未知 trace → 404
                miss = await client.get("/api/rca/unknown")
                assert miss.status_code == 404

    asyncio.run(scenario())


def test_app_module_getters_exposed() -> None:
    """app 模块对外暴露 get_bus/get_registry/get_gateway/get_session_store/get_llm。"""
    for name in ("get_bus", "get_registry", "get_gateway", "get_session_store", "get_llm"):
        assert hasattr(app_module, name)


def test_fake_intent_json_valid() -> None:
    """fake 意图 JSON 可被解析为合法 Intent（守护 fake 不漂移）。"""
    from backend.app.api._fakes import _FAKE_INTENT_JSON
    from backend.app.contracts.intent import Intent

    Intent.model_validate(json.loads(_FAKE_INTENT_JSON))
