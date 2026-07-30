"""网络感知工具的 ToolSpec（D7）。

只读采集（ss）；命令执行由特权执行器经命令模板白名单完成（本模块不跑命令）。
解析见 parsers.parse_ss_listening。
"""

from __future__ import annotations

from backend.app.contracts.tool import ToolSpec

# network.ports：ss -tulnp 只读、无参 → R0。
NETWORK_PORTS = ToolSpec(
    name="network.ports",
    description="列出本机监听端口（协议、本地地址:端口、占用进程）。",
    risk="R0",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    requires_roles=["operator"],
    reversible=True,
)

SPECS: list[ToolSpec] = [NETWORK_PORTS]
