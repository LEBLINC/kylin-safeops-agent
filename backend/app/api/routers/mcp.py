"""MCP 协议面（JSON-RPC 2.0 over HTTP）：initialize / tools/list / tools/call。

赛题要求"基于 MCP 协议"，此前仓内只有 to_mcp_tool() 转换函数而**无任何运行时
协议端点**——评委用 curl 发 JSON-RPC 拿不到任何东西。本模块把已有能力接出来，
零新依赖：工具清单复用 gateway.list_tools() + to_mcp_tool()，
调用复用 gateway.call()（完整三道闸 + 结果闸，不绕过任何安全边界）。

安全边界（与 /api/tools/call 同口径，见 routers/tools.py）：
- 只读门：非只读工具在此端点一律拒（变更类必须走 chat→审批链路）。
  MCP 客户端是外部程序，给它变更能力等于绕开人工确认闸。
- 错误一律回标准 JSON-RPC error 对象，不裸抛 500：协议面必须自洽，
  客户端靠 error.code 分支，拿到 HTML 500 页面只能当作服务挂了。

JSON-RPC 错误码（遵循规范 + MCP 惯例）：
  -32700 解析错误 / -32600 非法请求 / -32601 方法不存在
  -32602 参数非法（工具不存在、schema 不符）
  -32603 内部错误
  -32000 策略拒绝（应用级：被安全闸拦下，非协议错误）
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from backend.app.api.app import get_gateway
from backend.app.api.deps import verify_token
from backend.app.contracts.intent import CandidateTool
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.protocol import to_mcp_tool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])

#: 本服务实现的 MCP 协议版本（date-based，MCP 规范惯例）。
PROTOCOL_VERSION = "2024-11-05"

_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603
_POLICY_DENIED = -32000


def _error(req_id: Any, code: int, message: str, data: dict | None = None) -> dict:
    """构造 JSON-RPC error 响应。id 为 None 时按规范仍需回 null。"""
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _result(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _tool_to_dict(tool) -> dict:  # noqa: ANN001
    """MCP Tool dataclass → JSON-RPC 可序列化 dict（保持 inputSchema 驼峰）。"""
    out: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description or "",
        "inputSchema": tool.inputSchema,
    }
    if tool.meta:
        out["meta"] = tool.meta
    return out


@router.post("", summary="MCP JSON-RPC 端点（initialize / tools/list / tools/call）")
async def mcp_endpoint(
    request: Request,
    _user: str = Depends(verify_token),  # noqa: ARG001
    gateway: MCPGateway = Depends(get_gateway),
) -> dict:
    """MCP JSON-RPC 2.0 单端点分发。

    所有失败路径都回 JSON-RPC error 对象（HTTP 仍 200）——协议错误由 error.code
    承载是 JSON-RPC 的语义，用 HTTP 4xx/5xx 表达会让客户端无法区分
    "传输失败"与"方法执行被拒"。
    """
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 请求体不是合法 JSON
        return _error(None, _PARSE_ERROR, "Parse error: request body is not valid JSON")

    if not isinstance(payload, dict):
        return _error(None, _INVALID_REQUEST, "Invalid Request: payload must be a JSON object")

    req_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    if not isinstance(method, str):
        return _error(req_id, _INVALID_REQUEST, "Invalid Request: 'method' must be a string")
    if not isinstance(params, dict):
        return _error(req_id, _INVALID_PARAMS, "Invalid params: 'params' must be an object")

    if method == "initialize":
        return _result(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "kylin-safeops-agent", "version": "1.0"},
            },
        )

    if method == "tools/list":
        tools = [_tool_to_dict(to_mcp_tool(spec)) for spec in gateway.list_tools()]
        return _result(req_id, {"tools": tools})

    if method == "tools/call":
        return await _handle_tools_call(req_id, params, gateway)

    return _error(req_id, _METHOD_NOT_FOUND, f"Method not found: {method}")


async def _handle_tools_call(req_id: Any, params: dict, gateway: MCPGateway) -> dict:
    """tools/call：只读门 + gateway 三道闸；任何拒绝都回 JSON-RPC error。"""
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(name, str) or not name:
        return _error(req_id, _INVALID_PARAMS, "Invalid params: 'name' is required")
    if not isinstance(arguments, dict):
        return _error(req_id, _INVALID_PARAMS, "Invalid params: 'arguments' must be an object")

    known = {spec.name for spec in gateway.list_tools()}
    if name not in known:
        return _error(req_id, _INVALID_PARAMS, f"Unknown tool: {name}")

    candidate = CandidateTool(name=name, args=arguments)

    # 只读门（与 /api/tools/call 同口径）：变更类工具绝不经 MCP 外部端点执行。
    # 这是防御纵深——即便策略引擎误配返回 allow，此处也拦下。
    if not gateway.is_read_only(candidate):
        return _error(
            req_id,
            _POLICY_DENIED,
            "Tool requires human approval and cannot be called via MCP",
            {"tool": name, "reason": "change tools must go through chat→approval workflow"},
        )

    try:
        outcome = await gateway.call(candidate)
    except Exception as exc:  # noqa: BLE001 协议面必须自洽，绝不裸抛 500
        logger.exception("MCP tools/call 执行异常: tool=%s", name)
        return _error(
            req_id,
            _INTERNAL_ERROR,
            "Internal error during tool execution",
            {"tool": name, "error_class": type(exc).__name__},
        )

    if not outcome.executed:
        verdict = outcome.verdict.model_dump() if outcome.verdict is not None else None
        return _error(
            req_id,
            _POLICY_DENIED,
            outcome.reason or "Tool call denied by policy",
            {"tool": name, "verdict": verdict},
        )

    result = outcome.result
    text = result.stdout_truncated if result is not None else ""
    return _result(
        req_id,
        {
            "content": [{"type": "text", "text": text}],
            "isError": bool(result is not None and result.exit_code != 0),
        },
    )
