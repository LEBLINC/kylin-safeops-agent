"""工具名 → 解析器 分派（把 ToolResult.stdout 转结构化观测）。

约定（TODO(BLOCKED-ON-EXECUTOR): 待确认 Executor.execute() 的 stdout_truncated 真实格式）：
- 本骨架假定 ToolResult.stdout_truncated 为对应命令的**原始文本 stdout**
  （df/ps/ss/journalctl/sha256sum 等的直接输出）。
- parse_tool_result 按工具名分派到 os_ops/parsers 的对应纯解析器，所需可选参数
  从 ToolResult.args 取。
- 返回结构化 pydantic 模型；无对应解析器（变更工具、需基线/多命令聚合的工具）返回 None，
  调用方据此回退到原始 stdout。

安全：仅解析不可信 stdout，不执行命令、不拼 shell。结构化结果若回喂 LLM 仍须
经回喂封装（feedback.wrap_*）定界隔离。
"""

from __future__ import annotations

from pydantic import BaseModel

from backend.app.contracts.untrusted import ToolResult
from mcp_servers.os_ops import parsers

_MB = 1024 * 1024


def parse_tool_result(result: ToolResult) -> BaseModel | None:
    """按 result.tool 分派到对应解析器，返回结构化模型；无解析器则 None。"""
    tool = result.tool
    stdout = result.stdout_truncated
    args = result.args

    if tool == "disk.usage":
        return parsers.parse_df_output(stdout)
    if tool == "disk.large_files":
        return parsers.parse_find_size_output(
            stdout,
            min_size_bytes=int(args.get("min_size_mb", 0)) * _MB,
            top_n=args.get("top_n"),
        )
    if tool == "process.list":
        return parsers.parse_ps_output(
            stdout, sort_by=str(args.get("sort_by", "cpu")), top_n=args.get("top_n")
        )
    if tool == "system.cpu_load":
        return parsers.parse_vmstat_output(stdout)
    if tool == "system.mem_usage":
        return parsers.parse_free_output(stdout)
    if tool == "network.ports":
        return parsers.parse_listening_ports(stdout)  # 自动兼容 ss/netstat（D14 降级）
    if tool == "log.journal_query":
        return parsers.parse_journal_lines(stdout, unit=str(args.get("unit", "")))
    if tool == "log.large_log_scan":
        return parsers.parse_log_size_scan(
            stdout,
            min_size_bytes=int(args.get("min_size_mb", 0)) * _MB,
            top_n=args.get("top_n"),
        )
    if tool == "file.lsof_check":
        return parsers.parse_lsof_output(stdout)
    if tool == "service.status":
        return parsers.parse_systemctl_show(stdout, name=str(args.get("service_name", "")))
    if tool == "config.hash_snapshot":
        return parsers.parse_sha256sum_output(stdout)

    # 以下无单步解析器，返回 None 让调用方回退原始 stdout：
    # - system.info：需多命令聚合 dict（TODO(BLOCKED-ON-EXECUTOR): 约定多命令输出格式）
    # - config.diff：需基线快照对比（运行时/D 职责）
    # - log.compress_rotate / service.restart：变更类，结果为动作回执非可解析采集
    return None
