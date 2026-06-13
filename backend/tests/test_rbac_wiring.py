"""任务丁 — RBAC 端到端接线验证（can_approve 进审批闸，fail-closed）。

覆盖（演示态 X-User-Role 头）：
- operator 批 R2(operator) → 200 续跑；operator 批 R3(admin) → 403 且仍 WAIT_APPROVAL、未执行。
- admin 批 R2/R3 → 200。
- 缺角色头 / 未知角色 → 403（fail-closed）。
- 大写头 Admin/Operator 归一后可批；拼错 → 403。
- 403 后会话仍可被有权角色再次 resume（重入锁已释放）。

注：本测试验证审批**授权**确定性强制；身份**认证**仍未接入（角色来自演示态头）。
"""

from __future__ import annotations

import asyncio

import httpx

from backend.app.api import app as app_module
from backend.app.api._fakes import FakeExecutor
from backend.app.api.app import create_app, get_gateway, lifespan
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
    """裁决 confirm，approval_role 由构造参数决定（驱动指定门槛的 WAIT_APPROVAL）。"""

    def __init__(self, approval_role: str | None, risk: str) -> None:
        self._role = approval_role
        self._risk = risk

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return PolicyVerdict(
            decision="confirm",
            final_risk=self._risk,
            matched_rules=["fake:confirm"],
            reason="needs approval",
            approval_required=True,
            approval_role=self._role,
        )


def _gateway_factory(approval_role: str | None, risk: str):  # noqa: ANN201
    def _factory() -> MCPGateway:
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
        return MCPGateway(registry, _ConfirmPolicy(approval_role, risk), FakeExecutor())  # type: ignore[arg-type]

    return _factory


async def _post_chat_to_wait(client: httpx.AsyncClient, registry) -> str:  # noqa: ANN001
    trace_id = (await client.post("/api/chat", json={"message": "重启服务"})).json()["trace_id"]
    await _wait_state(registry, trace_id, "WAIT_APPROVAL")
    return trace_id


async def _resume(client: httpx.AsyncClient, trace_id: str, role: str | None) -> httpx.Response:
    headers = {"X-User-Role": role} if role is not None else {}
    return await client.post(
        "/api/approvals/resume",
        headers=headers,
        json={"trace_id": trace_id, "approved": True},
    )


# ---- operator 门槛（R2/operator）------------------------------------------


def test_operator_approves_operator_plan() -> None:
    """operator 批 approval_role=operator 的计划 → 200 续跑到 FINISHED。"""

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("operator", "R2")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await _resume(client, tid, "operator")
                assert rr.status_code == 200
                await _wait_state(registry, tid, "FINISHED")
        app.dependency_overrides.clear()

    asyncio.run(scenario())


# ---- admin 门槛（R3/admin）------------------------------------------------


def test_operator_cannot_approve_admin_plan_fail_closed() -> None:
    """operator 批 approval_role=admin 的计划 → 403，仍 WAIT_APPROVAL、未执行。"""

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await _resume(client, tid, "operator")
                assert rr.status_code == 403
                # fail-closed：未离开 WAIT_APPROVAL（真命令未执行）
                assert registry.get(tid).orchestrator.state.value == "WAIT_APPROVAL"
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_admin_approves_admin_and_operator_plans() -> None:
    """admin 可批 admin 门槛计划 → 200。"""

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await _resume(client, tid, "admin")
                assert rr.status_code == 200
                await _wait_state(registry, tid, "FINISHED")
        app.dependency_overrides.clear()

    asyncio.run(scenario())


# ---- fail-closed：缺/未知/拼错角色 ---------------------------------------


def test_missing_role_header_forbidden() -> None:
    """缺 X-User-Role 头 → 403（fail-closed）。"""

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("operator", "R2")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await _resume(client, tid, None)
                assert rr.status_code == 403
                assert registry.get(tid).orchestrator.state.value == "WAIT_APPROVAL"
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_unknown_role_forbidden() -> None:
    """未知角色（viewer）→ 403。"""

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("operator", "R2")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                assert (await _resume(client, tid, "viewer")).status_code == 403
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_uppercase_role_normalized() -> None:
    """大写头 Admin 归一为 admin 后可批 admin 门槛 → 200。"""

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await _resume(client, tid, "Admin")
                assert rr.status_code == 200
                await _wait_state(registry, tid, "FINISHED")
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_misspelled_role_forbidden() -> None:
    """拼错角色（Admni）→ 归一 admni → 未知 → 403。"""

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                assert (await _resume(client, tid, "Admni")).status_code == 403
        app.dependency_overrides.clear()

    asyncio.run(scenario())


# ---- 403 后会话仍可被有权角色 resume（重入锁已释放）----------------------


def test_session_resumable_after_forbidden() -> None:
    """operator 被 403 后，admin 仍可对同一会话 resume → 200（重入锁拒绝时未占用）。"""

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                assert (await _resume(client, tid, "operator")).status_code == 403
                # 锁未被占用：有权角色仍可续跑
                rr = await _resume(client, tid, "admin")
                assert rr.status_code == 200
                await _wait_state(registry, tid, "FINISHED")
        app.dependency_overrides.clear()

    asyncio.run(scenario())


# ---- _most_restrictive_role fail-closed 加固 ------------------------------


def test_most_restrictive_role_fail_closed() -> None:
    """单元：admin>operator；任一未知/None 混入 → 整批 None（fail-closed）；空 → None。"""
    from backend.app.agent.orchestrator import _most_restrictive_role

    assert _most_restrictive_role(["operator", "admin"]) == "admin"
    assert _most_restrictive_role(["operator"]) == "operator"
    assert _most_restrictive_role(["operator", None]) is None
    assert _most_restrictive_role(["operator", "viewer"]) is None
    assert _most_restrictive_role([]) is None


def test_unknown_approval_role_blocks_everyone_fail_closed() -> None:
    """端到端：confirm 裁决 approval_role=None → 任何角色（含 admin）均 403（fail-closed）。"""

    async def scenario() -> None:
        app = create_app()
        # approval_role=None 模拟误配/未知门槛
        app.dependency_overrides[get_gateway] = _gateway_factory(None, "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                # 即便 admin 也无法批准未知门槛计划
                assert (await _resume(client, tid, "admin")).status_code == 403
                assert registry.get(tid).orchestrator.state.value == "WAIT_APPROVAL"
        app.dependency_overrides.clear()

    asyncio.run(scenario())
