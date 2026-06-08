"""系统信息感知工具的 ToolSpec（D6）。

只读采集；命令执行由 D 的 Executor 经命令模板白名单完成（本模块不跑命令）。
解析逻辑见 parsers.parse_system_info。
"""

from __future__ import annotations

from backend.app.contracts.tool import ToolSpec

# system.info：纯只读、无参数、无副作用 → R0。
SYSTEM_INFO = ToolSpec(
    name="system.info",
    description="获取系统基本信息：主机名、发行版、内核、架构、运行时长、上次启动时间。",
    risk="R0",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    requires_roles=["operator"],
    reversible=True,
)

SPECS: list[ToolSpec] = [SYSTEM_INFO]
