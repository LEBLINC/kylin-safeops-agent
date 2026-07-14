"""接线增量 — RBAC 真认证（反代签名身份）+ 拒批放宽 端到端验证（甲+乙）。

覆盖：
- proxy 模式（命门）：合法签名 admin 批 R3 → 200；operator 批 admin 门槛 → 403 且仍 WAIT；
  无签名/过期/**篡改 roles（声称 admin 但签名是 operator 的）→ 401**（裸头伪造角色已无效）。
- dev 模式（联调）：X-User-Role admin 批 R3 → 200；缺角色头 → 401；proxy 下裸 X-User-Role → 401。
- 拒批放宽（乙）：operator 签名拒批 admin 门槛 → 200（REJECTED、未执行）；批准 → 403；无签名 → 401。
- _most_restrictive_role fail-closed 单元 + 未知门槛端到端（任何角色 403）。

注：conftest 默认 KYLIN_AUTH_MODE=dev；proxy 用例 monkeypatch 覆盖回 proxy + 设共享密钥。
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from backend.app.api import app as app_module
from backend.app.api._fakes import FakeExecutor
from backend.app.api.app import create_app, get_gateway, lifespan
from backend.app.api.auth import sign_identity
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry

_SECRET = "test-proxy-secret"


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def _llm_fake_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """阶段5 step 2 收口 (ADR-0006): 默认真接 LLM; rbac 测试夹具显式 opt-in fake.

    rbac 走 fake 工具桩 (FakeExecutor) + 真接 LLM 不兼容 (无 API key).
    """
    monkeypatch.setenv("KYLIN_LLM_FAKE", "true")


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
    """裁决 confirm，approval_role 由构造参数决定。"""

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
                name="service.restart",
                description="重启服务",
                risk="R3",
                input_schema={
                    "type": "object",
                    "properties": {"service_name": {"type": "string", "minLength": 1}},
                    "required": ["service_name"],
                    "additionalProperties": False,
                },
                requires_roles=["admin"],
                reversible=False,
            )
        )
        return MCPGateway(registry, _ConfirmPolicy(approval_role, risk), FakeExecutor())  # type: ignore[arg-type]

    return _factory


def _signed_headers(
    user: str, roles_csv: str, *, sign_roles: str | None = None, ts: int | None = None
) -> dict[str, str]:
    """构造 proxy 签名头。sign_roles 不同于 roles_csv 时模拟篡改（声称 vs 实签）。"""
    timestamp = str(ts if ts is not None else int(time.time()))
    signature = sign_identity(
        user, sign_roles if sign_roles is not None else roles_csv, timestamp, _SECRET
    )
    return {
        "X-Auth-User": user,
        "X-Auth-Roles": roles_csv,
        "X-Auth-Timestamp": timestamp,
        "X-Auth-Signature": signature,
    }


async def _post_chat_to_wait(client: httpx.AsyncClient, registry) -> str:  # noqa: ANN001
    # 全量端点认证已接：proxy 模式下 /api/chat 也需签名身份（dev 模式忽略，无害）。
    trace_id = (
        await client.post(
            "/api/chat",
            headers=_signed_headers("system", "operator"),
            json={"message": "重启服务"},
        )
    ).json()["trace_id"]
    await _wait_state(registry, trace_id, "WAIT_APPROVAL")
    return trace_id


# ============================================================
# proxy 模式（命门：裸头伪造角色无效）
# ============================================================


def test_proxy_admin_signature_approves_admin_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：合法 admin 签名批 R3(admin) → 200 续跑到 FINISHED。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await client.post(
                    "/api/approvals/resume",
                    headers=_signed_headers("alice", "admin"),
                    json={"trace_id": tid, "approved": True},
                )
                assert rr.status_code == 200
                await _wait_state(registry, tid, "FINISHED")
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_proxy_operator_cannot_approve_admin_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：合法 operator 签名批 R3(admin 门槛) → 403 且仍 WAIT_APPROVAL。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await client.post(
                    "/api/approvals/resume",
                    headers=_signed_headers("bob", "operator"),
                    json={"trace_id": tid, "approved": True},
                )
                assert rr.status_code == 403
                assert registry.get(tid).orchestrator.state.value == "WAIT_APPROVAL"
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_proxy_no_signature_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：无签名头 → 401（fail-closed），真命令未执行、仍 WAIT_APPROVAL。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await client.post(
                    "/api/approvals/resume", json={"trace_id": tid, "approved": True}
                )
                assert rr.status_code == 401
                assert registry.get(tid).orchestrator.state.value == "WAIT_APPROVAL"
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_proxy_expired_timestamp_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy：时间戳超窗（防重放）→ 401。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                stale = int(time.time()) - 400  # 超 300s 窗
                rr = await client.post(
                    "/api/approvals/resume",
                    headers=_signed_headers("alice", "admin", ts=stale),
                    json={"trace_id": tid, "approved": True},
                )
                assert rr.status_code == 401
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_proxy_tampered_roles_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """★命门：声称 admin（X-Auth-Roles=admin）但签名是 operator 的 → 401（伪造角色无效）。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                # 头声称 admin，但签名按 operator 计算 → HMAC 不匹配
                headers = _signed_headers("mallory", "admin", sign_roles="operator")
                rr = await client.post(
                    "/api/approvals/resume",
                    headers=headers,
                    json={"trace_id": tid, "approved": True},
                )
                assert rr.status_code == 401
                assert registry.get(tid).orchestrator.state.value == "WAIT_APPROVAL"
        app.dependency_overrides.clear()

    asyncio.run(scenario())


# ============================================================
# dev 模式（联调，conftest 默认）
# ============================================================


def test_dev_mode_user_role_approves() -> None:
    """dev：X-User-Role admin 批 R3 → 200（证明 X 前端 dev 联调可用）。"""

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await client.post(
                    "/api/approvals/resume",
                    headers={"X-User-Role": "admin"},
                    json={"trace_id": tid, "approved": True},
                )
                assert rr.status_code == 200
                await _wait_state(registry, tid, "FINISHED")
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_dev_mode_missing_role_unauthorized() -> None:
    """dev：缺 X-User-Role → 401。"""

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await client.post(
                    "/api/approvals/resume", json={"trace_id": tid, "approved": True}
                )
                assert rr.status_code == 401
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_proxy_mode_bare_user_role_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """proxy 模式下纯 X-User-Role（无签名）→ 401（dev 演示态头在生产无效）。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await client.post(
                    "/api/approvals/resume",
                    headers={"X-User-Role": "admin"},
                    json={"trace_id": tid, "approved": True},
                )
                assert rr.status_code == 401
        app.dependency_overrides.clear()

    asyncio.run(scenario())


# ============================================================
# 拒批放宽（乙）
# ============================================================


def test_reject_relaxed_any_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """乙：operator 签名**拒批** admin 门槛 → 200（取消放行），终态 REJECTED、未执行。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await client.post(
                    "/api/approvals/resume",
                    headers=_signed_headers("bob", "operator"),
                    json={"trace_id": tid, "approved": False},
                )
                assert rr.status_code == 200
                await _wait_state(registry, tid, "REJECTED")
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_reject_still_requires_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    """乙：拒批也要已认证——无签名拒批 → 401。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory("admin", "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await client.post(
                    "/api/approvals/resume", json={"trace_id": tid, "approved": False}
                )
                assert rr.status_code == 401
        app.dependency_overrides.clear()

    asyncio.run(scenario())


# ============================================================
# _most_restrictive_role fail-closed
# ============================================================


def test_most_restrictive_role_fail_closed() -> None:
    """单元：admin>operator；任一未知/None 混入 → 整批 None（fail-closed）；空 → None。"""
    from backend.app.agent.orchestrator import _most_restrictive_role

    assert _most_restrictive_role(["operator", "admin"]) == "admin"
    assert _most_restrictive_role(["operator"]) == "operator"
    assert _most_restrictive_role(["operator", None]) is None
    assert _most_restrictive_role(["operator", "viewer"]) is None
    assert _most_restrictive_role([]) is None


def test_unknown_approval_role_blocks_everyone(monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：confirm 裁决 approval_role=None → 任何角色（含 admin 签名）批准均 403。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "proxy")
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _SECRET)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gateway_factory(None, "R3")
        async with lifespan(app):
            registry = app_module.get_registry()
            async with _client(app) as client:
                tid = await _post_chat_to_wait(client, registry)
                rr = await client.post(
                    "/api/approvals/resume",
                    headers=_signed_headers("alice", "admin"),
                    json={"trace_id": tid, "approved": True},
                )
                assert rr.status_code == 403
                assert registry.get(tid).orchestrator.state.value == "WAIT_APPROVAL"
        app.dependency_overrides.clear()

    asyncio.run(scenario())
