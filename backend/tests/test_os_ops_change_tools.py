"""D10 变更工具测试：log.compress_rotate (R2) / service.restart (R3)。

重点：变更工具风险分级正确、可逆性/角色正确、且经 gateway 时高危不被直接执行
（confirm 需审批、deny 拦死），证明变更工具不绕过策略闸。
"""

from __future__ import annotations

import asyncio

from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.untrusted import ToolResult
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from backend.app.mcp.schema_validator import validate_args
from mcp_servers.os_ops import all_specs
from mcp_servers.os_ops.tools_log import LOG_COMPRESS_ROTATE
from mcp_servers.os_ops.tools_service import SERVICE_RESTART


def test_change_tools_registered_with_correct_risk() -> None:
    specs = {s.name: s for s in all_specs()}
    assert specs["log.compress_rotate"].risk == "R2"
    assert specs["service.restart"].risk == "R3"
    # 可逆性 / 角色
    assert LOG_COMPRESS_ROTATE.reversible is True
    assert SERVICE_RESTART.reversible is False
    assert SERVICE_RESTART.requires_roles == ["admin"]


def test_compress_rotate_schema() -> None:
    assert validate_args({"path": "/var/log/app", "keep": 5}, LOG_COMPRESS_ROTATE.input_schema).ok
    assert not validate_args({"path": "var/log"}, LOG_COMPRESS_ROTATE.input_schema).ok  # ^/
    assert not validate_args({"path": "/v/../e"}, LOG_COMPRESS_ROTATE.input_schema).ok  # ..
    assert not validate_args({"path": "/x", "keep": 0}, LOG_COMPRESS_ROTATE.input_schema).ok


def test_restart_schema_rejects_injection() -> None:
    assert validate_args({"service_name": "nginx.service"}, SERVICE_RESTART.input_schema).ok
    assert not validate_args({"service_name": "nginx; rm -rf /"}, SERVICE_RESTART.input_schema).ok


# ---- gateway: 高危工具不绕过策略 -----------------------------------------


class _Policy:
    def __init__(self, decision: str) -> None:
        self.decision = decision

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return PolicyVerdict(
            decision=self.decision,
            final_risk="R3",
            matched_rules=["rule.highrisk"],
            reason="high risk change",
            approval_required=(self.decision == "confirm"),
            approval_role="admin" if self.decision == "confirm" else None,
        )


class _Executor:
    def __init__(self) -> None:
        self.calls: list[CandidateTool] = []

    async def execute(self, tool: CandidateTool) -> ToolResult:
        self.calls.append(tool)
        return ToolResult(tool=tool.name, args=tool.args, exit_code=0, stdout_truncated="ok")


def _gw(decision: str) -> tuple[MCPGateway, _Executor]:
    ex = _Executor()
    return MCPGateway(ToolRegistry(all_specs()), _Policy(decision), ex), ex


def test_restart_confirm_not_executed_without_approval() -> None:
    gw, ex = _gw("confirm")
    tool = CandidateTool(name="service.restart", args={"service_name": "nginx.service"})
    out = asyncio.run(gw.call(tool))
    assert not out.executed
    assert ex.calls == []  # 高危 confirm 未经审批，绝不执行


def test_restart_confirm_executes_after_approval() -> None:
    gw, ex = _gw("confirm")
    tool = CandidateTool(name="service.restart", args={"service_name": "nginx.service"})
    out = asyncio.run(gw.call(tool, approved=True))
    assert out.executed
    assert out.result is not None and out.result.is_untrusted is True
    assert len(ex.calls) == 1


def test_restart_deny_never_executes_even_if_approved() -> None:
    gw, ex = _gw("deny")
    tool = CandidateTool(name="service.restart", args={"service_name": "nginx.service"})
    out = asyncio.run(gw.call(tool, approved=True))
    assert not out.executed
    assert ex.calls == []  # deny 永远拦死，approved 也不放行
