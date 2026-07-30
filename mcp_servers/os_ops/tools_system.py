"""系统信息感知工具的 ToolSpec（D6）。

只读采集；命令执行由特权执行器经命令模板白名单完成（本模块不跑命令）。
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
    requires_roles=["viewer", "operator", "admin"],
    reversible=True,
)

# system.cpu_load：vmstat 1 秒采样 CPU 使用率（只读、无参、无副作用）→ R0。
# 命令模板/沙箱 profile=readonly/wrapper 白名单(/usr/bin/vmstat) 由执行层已就绪（阶段 2A）。
SYSTEM_CPU_LOAD = ToolSpec(
    name="system.cpu_load",
    description="采集 CPU 使用率（vmstat 1 秒采样：usage = 100 - idle）。",
    risk="R0",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    requires_roles=["viewer", "operator", "admin"],
    reversible=True,
)

# system.mem_usage：free -b 内存使用率（只读、无参、无副作用）→ R0。
# 命令模板/沙箱 profile=readonly/wrapper 白名单(/usr/bin/free) 由执行层已就绪（阶段 2A）。
SYSTEM_MEM_USAGE = ToolSpec(
    name="system.mem_usage",
    description="采集内存使用率（free -b：used = (total-available)/total）。",
    risk="R0",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    requires_roles=["viewer", "operator", "admin"],
    reversible=True,
)

SPECS: list[ToolSpec] = [SYSTEM_INFO, SYSTEM_CPU_LOAD, SYSTEM_MEM_USAGE]
