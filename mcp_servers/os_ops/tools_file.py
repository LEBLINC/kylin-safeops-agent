"""文件检查感知工具的 ToolSpec（D8）。

只读采集（lsof）；命令执行由 D 的 Executor 经命令模板白名单完成。
解析见 parsers.parse_lsof_output。
"""

from __future__ import annotations

from backend.app.contracts.tool import ToolSpec

# file.lsof_check：检查指定路径或进程的打开文件 → R0。
# 设计意图：path（绝对路径）或 pid（正整数）二选一。
# 现状（L-9 校准）：JSON Schema 子集校验器不支持 oneOf，**当前未做 path/pid 强制互斥**——
# 两参数都可选；策略层(guard)目前也不含该互斥语义校验，故"恰好一个"仅为约定，未强制。
# TODO：如需强制互斥，给 schema_validator 加 oneOf 子集支持，或在 dispatch 解析层显式校验。
FILE_LSOF_CHECK = ToolSpec(
    name="file.lsof_check",
    description="用 lsof 列出某路径或某 PID 占用的文件描述符（路径必须绝对）。",
    risk="R0",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "pattern": "^/"},
            "pid": {"type": "integer", "minimum": 1, "maximum": 4194304},
        },
        "additionalProperties": False,
    },
    requires_roles=["operator"],
    reversible=True,
)

SPECS: list[ToolSpec] = [FILE_LSOF_CHECK]
