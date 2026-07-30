"""命令模板白名单。

铁律：绝不 shell=True，绝不拼命令字符串。所有可执行命令在此声明，
args 以独立 argv 传入。模板里的占位符由 executor 安全替换。

首版路径按 Linux 通用路径（/usr/bin/...）；后续拿到麒麟 VM which 输出后
可精确到 VM 实际路径。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CommandTemplate:
    """一条命令模板。

    argv_prefix: 固定前缀，如 ["/usr/bin/df", "-PB1"]。
    dynamic_args: 动态参数名列表（按序），从 CandidateTool.args 取值拼成独立 argv。
    flag_map: 可选 flag 映射，如 {"unit": "-u", "priority": "-p"}。
    """

    argv_prefix: list[str]
    dynamic_args: list[str] = field(default_factory=list)
    flag_map: dict[str, str] = field(default_factory=dict)


# 工具名 → 命令变体名 → CommandTemplate。
# 命令变体用于 fallback（如 network.ports 有 ss 和 netstat 两个变体）。
COMMAND_TEMPLATES: dict[str, dict[str, CommandTemplate]] = {
    "system.info": {
        "default": CommandTemplate(
            argv_prefix=["echo"],  # 占位；system.info 需要多命令聚合，executor 特殊处理
        ),
    },
    "system.cpu_load": {
        "default": CommandTemplate(argv_prefix=["/usr/bin/vmstat", "1", "2"]),
    },
    "system.mem_usage": {
        "default": CommandTemplate(argv_prefix=["/usr/bin/free", "-b"]),
    },
    "disk.usage": {
        "default": CommandTemplate(argv_prefix=["/usr/bin/df", "-PB1"]),
    },
    "disk.large_files": {
        "default": CommandTemplate(
            argv_prefix=["/usr/bin/find"],
            dynamic_args=["path"],
            # find <path> -type f -printf "%s\t%p\n"
        ),
    },
    "process.list": {
        "default": CommandTemplate(argv_prefix=["/usr/bin/ps", "aux"]),
    },
    "network.ports": {
        "ss": CommandTemplate(argv_prefix=["/usr/sbin/ss", "-tulnp"]),
        "netstat": CommandTemplate(argv_prefix=["/usr/bin/netstat", "-tulnp"]),
    },
    "log.journal_query": {
        "default": CommandTemplate(
            argv_prefix=["/usr/bin/journalctl", "--no-pager"],
            flag_map={"unit": "-u", "priority": "-p", "since": "-S", "lines": "-n"},
        ),
    },
    "log.large_log_scan": {
        "default": CommandTemplate(
            argv_prefix=["/usr/bin/find"],
            dynamic_args=["path"],
        ),
    },
    "file.lsof_check": {
        "default": CommandTemplate(
            argv_prefix=["/usr/bin/lsof"],
            dynamic_args=["path"],
        ),
    },
    "service.status": {
        "default": CommandTemplate(
            argv_prefix=["/usr/bin/systemctl", "show"],
            dynamic_args=["service_name"],
        ),
    },
    "config.hash_snapshot": {
        "default": CommandTemplate(
            argv_prefix=["/usr/bin/sha256sum"],
            dynamic_args=["paths"],
        ),
    },
    # 变更类工具首版占位：subprocess v1 在 Windows 无法真执行，返回 exit_code=2
    "log.compress_rotate": {
        # gzip <file> 原地压缩：path 必须作为 argv 拼入，否则 gzip 无文件参数会读 stdin 卡死。
        "default": CommandTemplate(argv_prefix=["/usr/bin/gzip"], dynamic_args=["path"]),
    },
    "service.restart": {
        "default": CommandTemplate(
            argv_prefix=["/usr/bin/systemctl", "restart"],
            dynamic_args=["service_name"],
        ),
    },
}

#: 全局默认命令变体（无 fallback 声明时使用）。
DEFAULT_VARIANT = "default"


def get_template(tool_name: str, variant: str = DEFAULT_VARIANT) -> CommandTemplate | None:
    """按工具名+变体名取模板；未注册返回 None。"""
    variants = COMMAND_TEMPLATES.get(tool_name)
    if variants is None:
        return None
    return variants.get(variant)


def has_tool(tool_name: str) -> bool:
    return tool_name in COMMAND_TEMPLATES


def available_variants(tool_name: str) -> list[str]:
    """返回工具的所有命令变体名。"""
    return list(COMMAND_TEMPLATES.get(tool_name, {}).keys())
