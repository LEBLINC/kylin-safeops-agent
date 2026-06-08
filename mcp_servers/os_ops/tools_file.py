"""文件检查感知工具的 ToolSpec（D8）。

只读采集（lsof）；命令执行由 D 的 Executor 经命令模板白名单完成。
解析见 parsers.parse_lsof_output。
"""

from __future__ import annotations

from backend.app.contracts.tool import ToolSpec

# file.lsof_check：检查指定路径或进程的打开文件 → R0。
# 二选一参数：path（绝对路径）或 pid（正整数）。两者都给视为非法（exactly one）。
# JSON Schema 子集校验器不支持 oneOf，本期由两参数都可选 + 描述约束承载，
# 真实策略层（D 的 PolicyEngine）做语义校验；本期不做强 schema 互斥。
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
