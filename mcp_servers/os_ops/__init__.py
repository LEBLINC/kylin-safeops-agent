"""os_ops 感知工具集（部分文件改造自 linux-mcp-server，Apache-2.0）。

改造范围以 NOTICE 为准：仅 parsers.py / models.py 改造自 linux-mcp-server，
其余（各 tools_*.py 的 ToolSpec、dispatch、fallback 等）为本项目自写。
按 D6+ 逐批增长。提供 all_specs() 供 MCP Gateway 注册表加载。
本包只产 ToolSpec（risk + input_schema）+ 纯解析器；命令执行委托 D 的 Executor。
"""

from __future__ import annotations

from backend.app.contracts.tool import ToolSpec
from mcp_servers.os_ops import (
    tools_config,
    tools_disk,
    tools_file,
    tools_log,
    tools_network,
    tools_process,
    tools_service,
    tools_system,
)


def all_specs() -> list[ToolSpec]:
    """返回当前已实现的全部感知工具 ToolSpec（供 registry 注册）。"""
    return [
        *tools_system.SPECS,
        *tools_disk.SPECS,
        *tools_process.SPECS,
        *tools_network.SPECS,
        *tools_log.SPECS,
        *tools_file.SPECS,
        *tools_service.SPECS,
        *tools_config.SPECS,
    ]


__all__ = ["all_specs"]
