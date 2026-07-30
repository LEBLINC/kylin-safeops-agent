"""P1-6: requires_roles 值域按 risk 分层 + /api/tools/call 接工具级 RBAC。

修前全部 15 个工具（含 R0 只读）都写 requires_roles=["operator"]，viewer 角色
在值域里根本不存在——声明了却从不生效，且 viewer 连 system.info 都调不了。

  V-1 参数化遍历全部 spec，断言 risk → requires_roles 的映射成立
      （刻意不逐个硬编码期望值：新增工具漏配时这条会直接红）
  V-2 viewer 在值域内确实出现过（防"全填 operator 也能让 V-1 过"的退化）
  A-1 viewer 调 R0/R1 → 200        （防把 viewer 锁死这个反向故障）
  A-2 viewer 调 R2+  → 403         （防"声明了不执行"）
  A-3 operator 调 R2 → 非 403      （R2 由只读门另行处置，但不该是授权问题）
  A-4 operator 调 R3 → 403
  A-5 admin 全通（不因 RBAC 被拒）
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from mcp_servers.os_ops import all_specs

_SPECS = sorted(all_specs(), key=lambda s: s.name)

#: risk → 允许调用的角色集合。R0/R1 只读可观测，viewer 应能看；
#: R2 变更需 operator 起步；R3/R4 高危仅 admin。
_EXPECTED_BY_RISK: dict[str, set[str]] = {
    "R0": {"viewer", "operator", "admin"},
    "R1": {"viewer", "operator", "admin"},
    "R2": {"operator", "admin"},
    "R3": {"admin"},
    "R4": {"admin"},
}


@pytest.mark.parametrize("spec", _SPECS, ids=[s.name for s in _SPECS])
def test_v1_requires_roles_matches_risk_tier(spec) -> None:  # noqa: ANN001
    """V-1: 每个 ToolSpec 的 requires_roles 必须等于其 risk 档位的角色集合。"""
    expected = _EXPECTED_BY_RISK.get(spec.risk)
    assert expected is not None, f"V-1: 未知 risk 档位 {spec.risk}（{spec.name}）——映射表需补"
    assert set(spec.requires_roles) == expected, (
        f"V-1: {spec.name}(risk={spec.risk}) 的 requires_roles="
        f"{sorted(spec.requires_roles)}，应为 {sorted(expected)}"
    )


def test_v2_viewer_actually_present_in_value_domain() -> None:
    """V-2: viewer 必须真的出现在某些工具的值域里。

    单靠 V-1 无法排除"映射表和数据一起写错"的情形；这条独立钉住
    viewer 这个角色确实被启用了，而不是又一个声明了不生效的值。
    """
    viewer_tools = [s.name for s in _SPECS if "viewer" in s.requires_roles]
    assert viewer_tools, "V-2: 没有任何工具允许 viewer——viewer 角色仍是摆设"
    assert all(
        s.risk in ("R0", "R1") for s in _SPECS if "viewer" in s.requires_roles
    ), "V-2: viewer 出现在了 R2+ 工具上——只读角色不得触达变更工具"


def _real_gateway():  # noqa: ANN202
    """用真实 15 个 spec 的 registry；策略一律 allow，把裁决焦点留给 RBAC。"""
    from backend.app.contracts.intent import CandidateTool
    from backend.app.contracts.policy import PolicyVerdict
    from backend.app.contracts.untrusted import ToolResult
    from backend.app.mcp.gateway import MCPGateway
    from backend.app.mcp.registry import ToolRegistry

    class _Policy:
        def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
            return PolicyVerdict(
                decision="allow",
                final_risk="R0",
                matched_rules=[],
                reason="ok",
                approval_required=False,
            )

    class _Executor:
        async def execute(self, tool: CandidateTool) -> ToolResult:
            return ToolResult(tool=tool.name, args=tool.args, exit_code=0, stdout_truncated="ok")

    return MCPGateway(ToolRegistry(list(all_specs())), _Policy(), _Executor())


def _call_as(role: str, tool: str, args: dict | None = None) -> httpx.Response:
    """以指定角色打 POST /api/tools/call（dev 认证态，裸 X-User-Role）。"""
    from backend.app.api.app import create_app, get_gateway, lifespan

    async def scenario() -> httpx.Response:
        app = create_app()
        app.dependency_overrides[get_gateway] = _real_gateway
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post(
                    "/api/tools/call",
                    headers={"X-User-Role": role},
                    json={"tool": tool, "args": args or {}},
                )

    old = os.environ.get("KYLIN_AUTH_MODE")
    os.environ["KYLIN_AUTH_MODE"] = "dev"
    try:
        return asyncio.run(scenario())
    finally:
        if old is None:
            os.environ.pop("KYLIN_AUTH_MODE", None)
        else:
            os.environ["KYLIN_AUTH_MODE"] = old


def test_a1_viewer_can_call_readonly_tools() -> None:
    """A-1: viewer 调 R0 只读工具必须放行——防"把 viewer 锁死"的反向故障。"""
    resp = _call_as("viewer", "system.info")
    assert resp.status_code == 200, (
        f"A-1: viewer 调 R0 被拒（{resp.status_code}）——"
        f"viewer 被锁死在只读工具外：{resp.text[:200]}"
    )


def test_a2_viewer_cannot_call_change_tools() -> None:
    """A-2: viewer 调 R2 变更工具必须 403——声明的值域要真生效。"""
    resp = _call_as("viewer", "log.compress_rotate", {"path": "/var/log/x.log"})
    assert resp.status_code == 403, (
        f"A-2: viewer 调 R2 未被 403 拦下（实际 {resp.status_code}）——"
        f"requires_roles 声明了却不执行"
    )


def test_a3_operator_r2_not_rejected_by_rbac() -> None:
    """A-3: operator 调 R2 不该因授权被拒。

    该端点另有只读门会把 R2 挡成 200+executed=False（S6 防御纵深），
    故这里只断言"不是 403"——RBAC 与只读门是两道独立的闸，不能互相顶替。
    """
    resp = _call_as("operator", "log.compress_rotate", {"path": "/var/log/x.log"})
    assert resp.status_code != 403, "A-3: operator 有权调 R2，不该被工具级 RBAC 拒绝"


def test_a4_operator_cannot_call_r3() -> None:
    """A-4: operator 调 R3 高危工具必须 403。"""
    resp = _call_as("operator", "service.restart", {"service_name": "nginx"})
    assert resp.status_code == 403, f"A-4: operator 调 R3 未被拦下（实际 {resp.status_code}）"


def test_a5_admin_not_blocked_by_rbac() -> None:
    """A-5: admin 不因工具级 RBAC 被拒（各档位都试一遍）。"""
    for tool, args in (
        ("system.info", {}),
        ("log.compress_rotate", {"path": "/var/log/x.log"}),
        ("service.restart", {"service_name": "nginx"}),
    ):
        resp = _call_as("admin", tool, args)
        assert resp.status_code != 403, f"A-5: admin 调 {tool} 被 RBAC 拒绝"
