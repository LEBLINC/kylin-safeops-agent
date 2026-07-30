"""磁盘感知工具的 ToolSpec（D6）。

只读采集；命令执行由特权执行器经命令模板白名单完成（本模块不跑命令）。
解析见 parsers.parse_df_output / parse_find_size_output。
路径参数交 schema_validator 兜底（绝对路径 + 禁 ..）。
"""

from __future__ import annotations

from backend.app.contracts.tool import ToolSpec

# disk.usage：df 只读、无参 → R0。
DISK_USAGE = ToolSpec(
    name="disk.usage",
    description="获取各挂载点磁盘占用（大小、已用、可用、使用率、挂载点）。",
    risk="R0",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    requires_roles=["operator"],
    reversible=True,
)

# disk.large_files：扫描文件系统找大文件，只读但开销较大 → R1。
# path 必须绝对（^/）；schema_validator 另行拦截 ".." 逃逸。
DISK_LARGE_FILES = ToolSpec(
    name="disk.large_files",
    description="在指定路径下扫描大文件，按大小降序返回（可设最小阈值与数量上限）。",
    risk="R1",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "pattern": "^/",
            },
            "min_size_mb": {"type": "integer", "minimum": 0},
            "top_n": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    requires_roles=["operator"],
    reversible=True,
)

SPECS: list[ToolSpec] = [DISK_USAGE, DISK_LARGE_FILES]
