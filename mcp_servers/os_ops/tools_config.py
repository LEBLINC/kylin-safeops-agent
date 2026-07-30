"""配置漂移感知工具的 ToolSpec（D9，本项目自写——原仓 linux-mcp-server 无此能力）。

只读采集（sha256sum）；命令执行由特权执行器经命令模板白名单完成。
解析见 parsers.parse_sha256sum_output / diff_config_snapshots。
config.diff 的"基线快照"存取属运行时/D 职责，本模块只定义工具契约与纯 diff 逻辑。
"""

from __future__ import annotations

from backend.app.contracts.tool import ToolSpec

# 复用的路径数组 schema：每个元素必须绝对路径（^/），schema_validator 另拦 ..。
_PATHS_SCHEMA = {
    "type": "array",
    "items": {"type": "string", "minLength": 1, "pattern": "^/"},
    "minItems": 1,
    "maxItems": 200,
}

# config.hash_snapshot：对一组配置文件取 sha256 快照 → R0。
CONFIG_HASH_SNAPSHOT = ToolSpec(
    name="config.hash_snapshot",
    description="对一组配置文件计算 sha256 哈希快照（用于后续漂移检测）。",
    risk="R0",
    input_schema={
        "type": "object",
        "properties": {"paths": _PATHS_SCHEMA},
        "required": ["paths"],
        "additionalProperties": False,
    },
    requires_roles=["viewer", "operator", "admin"],
    reversible=True,
)

# config.diff：重新快照并与基线对比，报告漂移 → R0（只读）。
CONFIG_DIFF = ToolSpec(
    name="config.diff",
    description="对一组配置文件重新取哈希并与基线快照对比，报告新增/删除/变更。",
    risk="R0",
    input_schema={
        "type": "object",
        "properties": {
            "paths": _PATHS_SCHEMA,
            "baseline_id": {"type": "string", "minLength": 1, "maxLength": 128},
        },
        "required": ["paths"],
        "additionalProperties": False,
    },
    requires_roles=["viewer", "operator", "admin"],
    reversible=True,
)

SPECS: list[ToolSpec] = [CONFIG_HASH_SNAPSHOT, CONFIG_DIFF]
