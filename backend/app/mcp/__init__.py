"""MCP 网关层（手册 §3.3）：工具注册 / 结构校验 / 受控调用 / 协议适配。"""

from backend.app.mcp.gateway import CallOutcome, MCPGateway
from backend.app.mcp.protocol import Tool, from_mcp_tool, to_mcp_tool
from backend.app.mcp.registry import ToolRegistry
from backend.app.mcp.result_gate import seal_result
from backend.app.mcp.schema_validator import ValidationResult, validate_args

__all__ = [
    "ToolRegistry",
    "validate_args",
    "ValidationResult",
    "MCPGateway",
    "CallOutcome",
    "seal_result",
    "Tool",
    "to_mcp_tool",
    "from_mcp_tool",
]
