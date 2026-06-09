"""D11-d 解析器分派骨架测试（约定 stdout=raw 文本；TODO(BLOCKED-ON-D) 待确认真实格式）。"""

from __future__ import annotations

from backend.app.contracts.untrusted import ToolResult
from mcp_servers.os_ops.dispatch import parse_tool_result
from mcp_servers.os_ops.models import (
    DiskUsage,
    LargeFiles,
    ListeningPorts,
    ProcessList,
    ServiceStatus,
)

_MB = 1024 * 1024


def _tr(tool: str, stdout: str, args: dict | None = None) -> ToolResult:
    return ToolResult(tool=tool, args=args or {}, exit_code=0, stdout_truncated=stdout)


def test_dispatch_disk_usage() -> None:
    raw = "Filesystem 1B-blocks Used Available Capacity Mounted on\n/dev/sda1 1000 230 770 23% /\n"
    out = parse_tool_result(_tr("disk.usage", raw))
    assert isinstance(out, DiskUsage)
    assert out.filesystems[0].use_percent == 23


def test_dispatch_disk_large_files_uses_args() -> None:
    raw = f"{5 * _MB}\t/var/log/a\n{200 * _MB}\t/var/log/big\n"
    out = parse_tool_result(_tr("disk.large_files", raw, {"min_size_mb": 10, "top_n": 5}))
    assert isinstance(out, LargeFiles)
    assert [f.path for f in out.files] == ["/var/log/big"]


def test_dispatch_process_list_uses_sort_arg() -> None:
    raw = (
        "USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND\n"
        "root 1 0.1 0.5 1 2 ? Ss 10:00 0:01 init\n"
        "app 42 5.0 2.0 5 8 ? Sl 10:01 0:30 server\n"
    )
    out = parse_tool_result(_tr("process.list", raw, {"sort_by": "cpu"}))
    assert isinstance(out, ProcessList)
    assert out.processes[0].pid == 42


def test_dispatch_network_ports() -> None:
    raw = (
        "Netid State Recv-Q Send-Q Local Peer Process\n"
        'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=900,fd=3))\n'
    )
    out = parse_tool_result(_tr("network.ports", raw))
    assert isinstance(out, ListeningPorts)
    assert out.ports[0].local_port == "22"


def test_dispatch_service_status_uses_name_arg() -> None:
    raw = "ActiveState=active\nSubState=running\nMainPID=900\n"
    out = parse_tool_result(_tr("service.status", raw, {"service_name": "sshd.service"}))
    assert isinstance(out, ServiceStatus)
    assert out.name == "sshd.service"
    assert out.active_state == "active"


def test_dispatch_returns_none_for_unparseable() -> None:
    # system.info（需多命令聚合）、变更工具、config.diff → None（回退原始 stdout）
    assert parse_tool_result(_tr("system.info", "x")) is None
    assert parse_tool_result(_tr("service.restart", "ok", {"service_name": "nginx"})) is None
    assert parse_tool_result(_tr("config.diff", "x", {"paths": ["/etc/hosts"]})) is None
    assert parse_tool_result(_tr("unknown.tool", "x")) is None
