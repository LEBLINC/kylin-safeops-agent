"""D5 MCP Gateway 测试：结构校验、注册表、三道闸、协议往返。

fake policy/executor，不触网、不执行真命令。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.tool import ToolSpec
from backend.app.contracts.untrusted import ToolResult
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.protocol import from_mcp_tool, to_mcp_tool
from backend.app.mcp.registry import ToolRegistry
from backend.app.mcp.schema_validator import validate_args

# 一个典型只读工具规格：path 字符串 + 可选 min_size_mb 整数。
_DISK_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "min_size_mb": {"type": "integer", "minimum": 0},
    },
    "required": ["path"],
    "additionalProperties": False,
}
_DISK_SPEC = ToolSpec(
    name="disk.large_files",
    description="列出大文件",
    risk="R1",
    input_schema=_DISK_SCHEMA,
    requires_roles=["operator"],
    reversible=True,
)


# ---- schema_validator ----------------------------------------------------


def test_validate_args_ok() -> None:
    res = validate_args({"path": "/var/log", "min_size_mb": 500}, _DISK_SCHEMA)
    assert res.ok


def test_validate_args_missing_required() -> None:
    res = validate_args({"min_size_mb": 1}, _DISK_SCHEMA)
    assert not res.ok
    assert any("path" in e for e in res.errors)


def test_validate_args_rejects_additional_property() -> None:
    res = validate_args({"path": "/x", "shell": "rm -rf /"}, _DISK_SCHEMA)
    assert not res.ok
    assert any("additional property" in e for e in res.errors)


def test_validate_args_rejects_dotdot_traversal() -> None:
    res = validate_args({"path": "/var/../etc/shadow"}, _DISK_SCHEMA)
    assert not res.ok
    assert any(".." in e for e in res.errors)


def test_validate_args_type_mismatch_and_bool_not_int() -> None:
    assert not validate_args({"path": "/x", "min_size_mb": "big"}, _DISK_SCHEMA).ok
    # bool 不应被当作 integer
    assert not validate_args({"path": "/x", "min_size_mb": True}, _DISK_SCHEMA).ok


def test_validate_args_enum_and_bounds() -> None:
    schema = {
        "type": "object",
        "properties": {"mode": {"type": "string", "enum": ["fast", "deep"]}},
        "required": ["mode"],
        "additionalProperties": False,
    }
    assert validate_args({"mode": "fast"}, schema).ok
    assert not validate_args({"mode": "nuke"}, schema).ok


# ---- registry ------------------------------------------------------------


def test_registry_register_get_list() -> None:
    reg = ToolRegistry([_DISK_SPEC])
    assert reg.has("disk.large_files")
    assert reg.get("disk.large_files") is _DISK_SPEC
    assert reg.get("nope") is None
    assert [s.name for s in reg.list_tools()] == ["disk.large_files"]


def test_registry_rejects_duplicate() -> None:
    reg = ToolRegistry([_DISK_SPEC])
    with pytest.raises(ValueError):
        reg.register(_DISK_SPEC)


# ---- gateway: fakes ------------------------------------------------------


class FakePolicy:
    def __init__(self, decision: str = "allow") -> None:
        self.decision = decision

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return PolicyVerdict(
            decision=self.decision,
            final_risk="R1",
            matched_rules=["rule.x"],
            reason="test",
            approval_required=(self.decision == "confirm"),
        )


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[CandidateTool] = []

    async def execute(self, tool: CandidateTool) -> ToolResult:
        self.calls.append(tool)
        return ToolResult(tool=tool.name, args=tool.args, exit_code=0, stdout_truncated="ok")


def _gateway(decision: str = "allow") -> tuple[MCPGateway, FakeExecutor]:
    ex = FakeExecutor()
    gw = MCPGateway(ToolRegistry([_DISK_SPEC]), FakePolicy(decision), ex)
    return gw, ex


# ---- gateway: three gates ------------------------------------------------


def test_list_tools() -> None:
    gw, _ = _gateway()
    assert [s.name for s in gw.list_tools()] == ["disk.large_files"]


def test_call_unknown_tool_denied() -> None:
    gw, ex = _gateway()
    out = asyncio.run(gw.call(CandidateTool(name="ghost.tool", args={})))
    assert not out.executed
    assert out.verdict is not None and out.verdict.decision == "deny"
    assert ex.calls == []


def test_call_bad_args_denied_before_policy() -> None:
    """闸2 在闸3 之前：args 非法直接 deny，不调用执行器。"""
    gw, ex = _gateway()
    out = asyncio.run(gw.call(CandidateTool(name="disk.large_files", args={"path": "../x"})))
    assert not out.executed
    assert "schema validation failed" in out.reason
    assert ex.calls == []


def test_call_policy_deny_blocks_execution() -> None:
    gw, ex = _gateway(decision="deny")
    out = asyncio.run(gw.call(CandidateTool(name="disk.large_files", args={"path": "/x"})))
    assert not out.executed
    assert ex.calls == []


def test_call_policy_confirm_not_executed_in_gateway() -> None:
    gw, ex = _gateway(decision="confirm")
    out = asyncio.run(gw.call(CandidateTool(name="disk.large_files", args={"path": "/x"})))
    assert not out.executed
    assert ex.calls == []


def test_call_allow_executes_and_wraps_untrusted() -> None:
    gw, ex = _gateway(decision="allow")
    out = asyncio.run(gw.call(CandidateTool(name="disk.large_files", args={"path": "/x"})))
    assert out.executed
    assert out.result is not None and out.result.is_untrusted is True
    assert len(ex.calls) == 1


def test_call_forces_untrusted_when_executor_omits() -> None:
    class SneakyExecutor:
        async def execute(self, tool: CandidateTool) -> ToolResult:
            return ToolResult.model_construct(
                tool=tool.name,
                args={},
                exit_code=0,
                stdout_truncated="",
                is_untrusted=False,
                wrap_token="<<UNTRUSTED_TOOL_OUTPUT>>",
            )

    gw = MCPGateway(ToolRegistry([_DISK_SPEC]), FakePolicy("allow"), SneakyExecutor())
    out = asyncio.run(gw.call(CandidateTool(name="disk.large_files", args={"path": "/x"})))
    assert out.result is not None and out.result.is_untrusted is True


# ---- protocol roundtrip --------------------------------------------------


def test_protocol_roundtrip_preserves_security_fields() -> None:
    mcp_tool = to_mcp_tool(_DISK_SPEC)
    assert mcp_tool.inputSchema == _DISK_SCHEMA
    back = from_mcp_tool(mcp_tool)
    assert back.name == _DISK_SPEC.name
    assert back.risk == _DISK_SPEC.risk
    assert back.requires_roles == _DISK_SPEC.requires_roles
    assert back.reversible == _DISK_SPEC.reversible


def test_protocol_missing_meta_defaults_conservative() -> None:
    """无 _meta 的外部工具 → 保守默认 R4/admin/不可逆，宁严勿放。"""
    from mcp.types import Tool

    raw = Tool(name="ext.tool", description="d", inputSchema={"type": "object"})
    spec = from_mcp_tool(raw)
    assert spec.risk == "R4"
    assert spec.requires_roles == ["admin"]
    assert spec.reversible is False
