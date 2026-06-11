"""MCP 协议薄 adapter（手册 §3.3 / 决策1）。

本模块是内部 ToolSpec（契约1）与 MCP `tools/list` 形态之间的唯一转换点。

LoongArch 铁律（L-1 整改）：原依赖官方 `mcp` SDK 的 `mcp.types.Tool`，但 mcp 会传递
拉入 jsonschema→rpds-py(Rust)、pyjwt[crypto]→cryptography→cffi(C) 等编译型依赖，
与"运行时仅 pydantic-core 一件编译依赖"的铁律冲突，且全仓仅用到一个类型。
故改为**自写薄 Tool 类型**，移除 mcp 运行时依赖。字段保持 SDK 兼容形态
（name/description/inputSchema/meta），不改对外 tools/list 输出契约。

注意命名差异：MCP 用驼峰 inputSchema，我们契约用 input_schema。
ToolSpec 的 risk/requires_roles/reversible 是安全扩展，经 meta 命名空间携带。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.contracts.tool import RiskLevel, ToolSpec

# 安全扩展字段在 Tool.meta 下的命名空间键。
_META_KEY = "kylin_safeops"


@dataclass(frozen=True)
class Tool:
    """自写薄 MCP Tool 类型（替代 mcp.types.Tool，避免 mcp 拉回 Rust/C 传递依赖）。

    字段与 MCP SDK 的 Tool 形态兼容：name / description / inputSchema(驼峰) / meta。
    仅用于 ToolSpec ↔ MCP 形态转换；不承载行为，纯数据。
    """

    name: str
    description: str | None = None
    inputSchema: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] | None = None


def to_mcp_tool(spec: ToolSpec) -> Tool:
    """ToolSpec → MCP Tool；安全扩展字段塞进 meta。"""
    return Tool(
        name=spec.name,
        description=spec.description,
        inputSchema=spec.input_schema,
        meta={
            _META_KEY: {
                "risk": spec.risk,
                "requires_roles": spec.requires_roles,
                "reversible": spec.reversible,
            }
        },
    )


def from_mcp_tool(tool: Tool) -> ToolSpec:
    """MCP Tool → ToolSpec；从 meta 还原安全扩展，缺失则取保守默认。

    保守默认（meta 缺失时）：risk=R4（最高危）、requires_roles=["admin"]、
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
