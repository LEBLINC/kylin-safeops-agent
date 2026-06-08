"""进程感知工具的 ToolSpec（D7）。

只读采集（ps）；命令执行由 D 的 Executor 经命令模板白名单完成（本模块不跑命令）。
解析见 parsers.parse_ps_output。
"""

from __future__ import annotations

from backend.app.contracts.tool import ToolSpec

# process.list：ps aux 只读 → R0。可选按 cpu/mem 排序 + top_n。
PROCESS_LIST = ToolSpec(
    name="process.list",
    description="列出进程（用户/PID/CPU%/MEM%/RSS/状态/命令），可按 cpu 或 mem 降序并限量。",
    risk="R0",
    input_schema={
        "type": "object",
        "properties": {
            "sort_by": {"type": "string", "enum": ["cpu", "mem"]},
            "top_n": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        "additionalProperties": False,
    },
    requires_roles=["operator"],
    reversible=True,
)

SPECS: list[ToolSpec] = [PROCESS_LIST]
