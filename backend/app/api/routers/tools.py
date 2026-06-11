"""增量4：GET /api/tools/registry + POST /api/tools/call。

registry：列举已注册工具；★字段适配 ToolSpec.name → 输出键名 "tool"（前端用 tool）。
call：手动单工具调用，仍走 gateway.call 完整三道闸（注册+结构+策略）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.app import get_gateway
from backend.app.api.deps import verify_token
from backend.app.api.schemas import (
    ToolCallRequest,
    ToolCallResponse,
    ToolRegistryItem,
)
from backend.app.contracts.intent import CandidateTool
from backend.app.mcp.gateway import MCPGateway

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("/registry", response_model=list[ToolRegistryItem])
async def get_registry_list(
    _user: str = Depends(verify_token),
    gateway: MCPGateway = Depends(get_gateway),
) -> list[ToolRegistryItem]:
    """列举已注册工具规格（name → tool 字段适配）。"""
    return [
        ToolRegistryItem(
            tool=spec.name,
            description=spec.description,
            risk=spec.risk,
            input_schema=spec.input_schema,
        )
        for spec in gateway.list_tools()
    ]


@router.post("/call", response_model=ToolCallResponse)
async def post_tool_call(
    body: ToolCallRequest,
    _user: str = Depends(verify_token),
    gateway: MCPGateway = Depends(get_gateway),
) -> ToolCallResponse:
    """手动单工具调用：经 gateway 三道闸。被拦下则 executed=False + reason/verdict。

    防御纵深（S6）：手动端点**仅允许只读工具**——变更工具(R2+)必须走 chat→审批链路。
    不只信策略：即便策略引擎误配/有缺陷对变更工具返回 allow，本对外暴露端点也绝不执行，
    与观测阶段 is_read_only 兜底同一不变量（手动端点不充当审批旁路，此处用代码强制）。
    confirm 类工具同样被只读门拦在外（approved 默认 False 之外的第二道兜底）。
    """
    candidate = CandidateTool(name=body.tool, args=body.args)
    if not gateway.is_read_only(candidate):
        return ToolCallResponse(
            executed=False,
            reason=(
                "manual tool call restricted to read-only tools; "
                "change tools must go through chat→approval"
            ),
        )
    outcome = await gateway.call(candidate)
    return ToolCallResponse(
        executed=outcome.executed,
        result=outcome.result.model_dump() if outcome.result is not None else None,
        verdict=outcome.verdict.model_dump() if outcome.verdict is not None else None,
        reason=outcome.reason,
    )
