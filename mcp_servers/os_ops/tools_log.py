"""日志感知工具的 ToolSpec（D8）。

只读采集；命令执行由 D 的 Executor 经命令模板白名单完成（本模块不跑命令）。
解析见 parsers.parse_journal_lines / parse_log_size_scan。
unit/priority/since/transport 收紧为 enum 或 pattern，避免 args 偷渡注入参数。
"""

from __future__ import annotations

from backend.app.contracts.tool import ToolSpec

# log.journal_query：journalctl 只读 → R0。
# 字段约束：
#   - unit: 仅允许 a-zA-Z0-9._@-* 与 .service / .socket / .target 等典型字符；
#   - priority: enum（emerg/alert/crit/err/warning/notice/info/debug 或 0-7 数字字符串）；
#   - since: 收紧为白名单 token + 相对时间（-1h/-30m/-7d）+ ISO 时间格式；
#   - transport: enum（audit/driver/journal/kernel/stdout/syslog）；
#   - lines: 1..10000。
LOG_JOURNAL_QUERY = ToolSpec(
    name="log.journal_query",
    description="查询 systemd journal（按 unit / priority / since / transport / lines 过滤）。",
    risk="R0",
    input_schema={
        "type": "object",
        "properties": {
            "unit": {"type": "string", "maxLength": 200, "pattern": r"^[A-Za-z0-9._@\-\*]*$"},
            "priority": {
                "type": "string",
                "enum": [
                    "",
                    "emerg",
                    "alert",
                    "crit",
                    "err",
                    "warning",
                    "notice",
                    "info",
                    "debug",
                    "0",
                    "1",
                    "2",
                    "3",
                    "4",
                    "5",
                    "6",
                    "7",
                ],
            },
            "since": {
                "type": "string",
                "maxLength": 40,
                "pattern": r"^(today|yesterday|-\d+[mhd]|\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?)?$",
            },
            "transport": {
                "type": "string",
                "enum": ["", "audit", "driver", "journal", "kernel", "stdout", "syslog"],
            },
            "lines": {"type": "integer", "minimum": 1, "maximum": 10000},
        },
        "additionalProperties": False,
    },
    requires_roles=["operator"],
    reversible=True,
)

# log.large_log_scan：扫日志大文件，路径必须绝对 → R1。
LOG_LARGE_LOG_SCAN = ToolSpec(
    name="log.large_log_scan",
    description="在指定路径下扫描大日志文件（*.log 等），按大小降序返回。",
    risk="R1",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "pattern": "^/"},
            "min_size_mb": {"type": "integer", "minimum": 0},
            "top_n": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    requires_roles=["operator"],
    reversible=True,
)

# ---- 变更工具（D10）：只声明契约，执行只经 D 的特权代理 + 策略 + 审批 ----

# log.compress_rotate：压缩并轮转日志（变更类）→ R2。
# 可逆性：压缩件保留可还原，标 reversible=True；但属写操作，必经策略放行（R2 通常 confirm）。
LOG_COMPRESS_ROTATE = ToolSpec(
    name="log.compress_rotate",
    description="压缩指定日志文件/目录，释放磁盘空间。",
    risk="R2",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "pattern": "^/"},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    requires_roles=["operator"],
    reversible=True,
)

SPECS: list[ToolSpec] = [LOG_JOURNAL_QUERY, LOG_LARGE_LOG_SCAN, LOG_COMPRESS_ROTATE]
