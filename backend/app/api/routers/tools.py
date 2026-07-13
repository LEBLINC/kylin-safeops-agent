"""增量4：GET /api/tools/registry + POST /api/tools/call。

registry：列举已注册工具；★字段适配 ToolSpec.name → 输出键名 "tool"（前端用 tool）。
call：手动单工具调用，仍走 gateway.call 完整三道闸（注册+结构+策略）。

D6 新增：GET /api/tools/calls/{call_id} — 单条工具调用详情（从审计库派生）。
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from backend.app.agent.ports import AuditSink
from backend.app.api.app import get_audit, get_gateway
from backend.app.api.deps import verify_token
from backend.app.api.schemas import (
    ToolCallDetail,
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


@router.get("/calls/{call_id}", response_model=ToolCallDetail)
async def get_tool_call_detail(
    call_id: str,
    _user: str = Depends(verify_token),
    audit: AuditSink = Depends(get_audit),
) -> ToolCallDetail:
    """D6 新增：单条工具调用详情（MVP call_id = trace_id）。

    数据来源：审计库 phase=EXECUTING|EXECUTED + 该 trace 末条记录
    （payload.tool/args/exit_code + created_at）。
    trace_id 找不到 / 无对应阶段记录 → 404（与 audit/traces/{trace_id} 行为对齐）。

    S9：payload 中敏感字段（api_key 等）已 SqliteAuditSink.get_trace_records 过滤；
    本端点复用 _conn 直查时也走相同黑名单（_SENSITIVE_KEYS）过滤，避免明文凭据返出。
    """
    from backend.app.audit.audit_logger import SqliteAuditSink

    conn = getattr(audit, "_conn", None)
    if conn is None:
        # 非 SqliteAuditSink 实现（如测试用 FakeAudit）→ 404
        raise HTTPException(status_code=404, detail=f"unknown call_id: {call_id}")

    # 找该 trace 末条 EXECUTING/EXECUTED 记录
    sql = (
        "SELECT seq, payload, created_at FROM audit_records "
        "WHERE trace_id = ? AND phase IN ('EXECUTING', 'EXECUTED') "
        "ORDER BY seq DESC LIMIT 1"
    )
    row = conn.execute(sql, (call_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown call_id: {call_id}")

    try:
        payload = json.loads(row["payload"])
    except (json.JSONDecodeError, TypeError):
        payload = {}

    # S9：payload 敏感字段过滤（与 audit_logger._SENSITIVE_KEYS 同口径）
    sensitive_keys = getattr(audit, "_SENSITIVE_KEYS", SqliteAuditSink._SENSITIVE_KEYS)
    raw_args = payload.get("args", {})
    if isinstance(raw_args, dict):
        safe_args = {
            k: ("***REDACTED***" if k.lower() in sensitive_keys else v) for k, v in raw_args.items()
        }
    else:
        safe_args = {}

    # created_at ISO 字符串 → epoch 秒
    try:
        ts = datetime.fromisoformat(row["created_at"]).timestamp()
    except (TypeError, ValueError):
        ts = 0.0

    return ToolCallDetail(
        call_id=call_id,
        trace_id=call_id,
        seq=int(row["seq"]),
        tool_name=str(payload.get("tool", "")),
        args=safe_args,
        exit_code=int(payload.get("exit_code", 0)),
        timestamp=ts,
    )
