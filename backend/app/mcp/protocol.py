"""MCP 协议薄 adapter（手册 §3.3 / 决策1）。

基于官方 mcp Python SDK（pin v1.x）。本模块是我们内部 ToolSpec（契约1）与
SDK 的 mcp.types.Tool 之间的唯一转换点——把对 SDK 的依赖收敛到这里，
SDK 升级/字段变动只需改本文件，不波及 registry/gateway/orchestrator。

注意命名差异：SDK 用驼峰 inputSchema，我们契约用 input_schema。
SDK 的 Tool 无 risk/requires_roles/reversible 概念，这些是我们的安全扩展，
经 tools/list 暴露时放进 Tool._meta 供前端/客户端读取。
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

from backend.app.contracts.tool import RiskLevel, ToolSpec

# 安全扩展字段在 MCP Tool._meta 下的命名空间键。
_META_KEY = "kylin_safeops"


def to_mcp_tool(spec: ToolSpec) -> Tool:
    """ToolSpec → MCP Tool；安全扩展字段塞进 _meta。"""
    return Tool(
        name=spec.name,
        description=spec.description,
        inputSchema=spec.input_schema,
        _meta={
            _META_KEY: {
                "risk": spec.risk,
                "requires_roles": spec.requires_roles,
                "reversible": spec.reversible,
            }
        },
    )


def from_mcp_tool(tool: Tool) -> ToolSpec:
    """MCP Tool → ToolSpec；从 _meta 还原安全扩展，缺失则取保守默认。

    保守默认（_meta 缺失时）：risk=R4（最高危）、requires_roles=["admin"]、
    reversible=False —— 宁可过严，不可误放行未知来源工具。
    """
    meta: dict[str, Any] = {}
    if tool.meta and isinstance(tool.meta.get(_META_KEY), dict):
        meta = tool.meta[_META_KEY]
    risk: RiskLevel = meta.get("risk", "R4")
    return ToolSpec(
        name=tool.name,
        description=tool.description or "",
        risk=risk,
        input_schema=tool.inputSchema,
        requires_roles=meta.get("requires_roles", ["admin"]),
        reversible=meta.get("reversible", False),
    )
