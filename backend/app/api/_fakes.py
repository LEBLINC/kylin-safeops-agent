"""联调注入桩集中地（待 D/X 真实现替换）。

本文件所有内容均为【注入桩 / fake】，仅用于联调与空跑：
- FakePolicyEngine / FakeExecutor → 待 D 的 backend/app/security、executor 真实现替换。
- _build_fake_gateway → 装配 fake 网关；真实现就位后删此 import、换真模块注入。
- fake LLMAdapter → 待接真实 LLM 端点替换。

替换面收敛于此：D/X 模块就绪后，改 app.py 的 import 指向真模块即可，
不必在 lifespan 里翻找内联的桩类。
"""

from __future__ import annotations

from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.tool import ToolSpec
from backend.app.contracts.untrusted import ToolResult
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry


class FakePolicyEngine:
    """注入桩：永远 allow。待 D 的 PolicyEngine.evaluate 真实现替换。"""

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return PolicyVerdict(
            decision="allow",
            final_risk="R0",
            matched_rules=[],
            reason="fake policy: allow all",
            approval_required=False,
        )


class FakeExecutor:
    """注入桩：永远返回成功空结果。待 D 的 Executor 真实现替换。"""

    async def execute(self, tool: CandidateTool) -> ToolResult:
        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=0,
            stdout_truncated="[fake] executed successfully",
            is_untrusted=True,
        )


def build_fake_gateway() -> MCPGateway:
    """装配 fake MCPGateway 用于空跑/联调（注入桩，待真实现替换）。"""
    registry = ToolRegistry()
    # 注册一个示例工具供 /api/tools/registry 联调
    registry.register(
        ToolSpec(
            name="system.overview",
            description="获取系统概览信息",
            risk="R0",
            input_schema={"type": "object", "properties": {}},
            requires_roles=["operator"],
            reversible=True,
        )
    )
    return MCPGateway(
        registry=registry,
        policy=FakePolicyEngine(),  # type: ignore[arg-type]
        executor=FakeExecutor(),  # type: ignore[arg-type]
    )
