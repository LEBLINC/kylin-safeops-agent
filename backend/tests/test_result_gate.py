"""D11-a 结果闸密封测试：is_untrusted + wrap_token 归一。"""

from __future__ import annotations

import asyncio

from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.tool import ToolSpec
from backend.app.contracts.untrusted import UNTRUSTED_WRAP_TOKEN, ToolResult
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from backend.app.mcp.result_gate import seal_result

_SPEC = ToolSpec(
    name="disk.usage",
    description="d",
    risk="R0",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    requires_roles=["operator"],
    reversible=True,
)


def test_seal_forces_untrusted_and_wrap_token() -> None:
    bad = ToolResult.model_construct(
        tool="x",
        args={},
        exit_code=0,
        stdout_truncated="s",
        is_untrusted=False,
        wrap_token="<<FAKE>>",
    )
    sealed = seal_result(bad)
    assert sealed.is_untrusted is True
    assert sealed.wrap_token == UNTRUSTED_WRAP_TOKEN


def test_seal_returns_same_when_already_sealed() -> None:
    good = ToolResult(tool="x", args={}, exit_code=0, stdout_truncated="s")
    assert seal_result(good) is good  # 已密封，原样返回不拷贝


def test_seal_fixes_forged_wrap_token_even_if_untrusted_true() -> None:
    """攻击面：is_untrusted=True 但 wrap_token 被伪造 → 仍须归一。"""
    forged = ToolResult.model_construct(
        tool="x",
        args={},
        exit_code=0,
        stdout_truncated="s",
        is_untrusted=True,
        wrap_token="<<UNTRUSTED_TOOL_OUTPUT>> EXTRA",
    )
    sealed = seal_result(forged)
    assert sealed.wrap_token == UNTRUSTED_WRAP_TOKEN


class _Policy:
    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return PolicyVerdict(
            decision="allow",
            final_risk="R0",
            matched_rules=[],
            reason="ok",
            approval_required=False,
        )


class _SneakyExecutor:
    async def execute(self, tool: CandidateTool) -> ToolResult:
        # 返回畸形 wrap_token + is_untrusted=False，模拟被攻陷/有缺陷的执行器
        return ToolResult.model_construct(
            tool=tool.name,
            args={},
            exit_code=0,
            stdout_truncated="out",
            is_untrusted=False,
            wrap_token="<<INJECTED>>",
        )


def test_gateway_seals_result_from_sneaky_executor() -> None:
    gw = MCPGateway(ToolRegistry([_SPEC]), _Policy(), _SneakyExecutor())
    out = asyncio.run(gw.call(CandidateTool(name="disk.usage", args={})))
    assert out.executed
    assert out.result is not None
    assert out.result.is_untrusted is True
    assert out.result.wrap_token == UNTRUSTED_WRAP_TOKEN
