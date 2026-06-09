"""D14 命令缺失降级测试：ss/netstat 双格式解析 + fallback 声明 + 空输入鲁棒。"""

from __future__ import annotations

from mcp_servers.os_ops.fallback import FALLBACK_COMMANDS, candidate_commands
from mcp_servers.os_ops.parsers import (
    parse_listening_ports,
    parse_netstat_listening,
    parse_ss_listening,
)

_SS = (
    "Netid State Recv-Q Send-Q Local Peer Process\n"
    'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=900,fd=3))\n'
)
_NETSTAT = (
    "Active Internet connections (only servers)\n"
    "Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program\n"
    "tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      900/sshd\n"
    "tcp6       0      0 :::80                   :::*                    LISTEN      1200/nginx\n"
    "udp        0      0 0.0.0.0:68              0.0.0.0:*                           512/dhclient\n"
)


def test_fallback_declaration() -> None:
    assert candidate_commands("network.ports") == ["ss", "netstat"]
    assert candidate_commands("unknown.tool") == []
    # 返回副本，外部修改不污染声明
    candidate_commands("network.ports").append("x")
    assert FALLBACK_COMMANDS["network.ports"] == ["ss", "netstat"]


def test_parse_netstat_listening() -> None:
    lp = parse_netstat_listening(_NETSTAT)
    assert len(lp.ports) == 3
    assert lp.ports[0].protocol == "TCP"
    assert lp.ports[0].local_port == "22"
    assert "900/sshd" in lp.ports[0].process
    # IPv6 :::80 端口正确分割
    assert lp.ports[1].local_port == "80"
    # udp 无 State 列也能解析，进程取含 '/' 的字段
    assert lp.ports[2].protocol == "UDP"
    assert "512/dhclient" in lp.ports[2].process


def test_auto_detect_picks_netstat() -> None:
    lp = parse_listening_ports(_NETSTAT)
    assert len(lp.ports) == 3


def test_auto_detect_picks_ss() -> None:
    lp = parse_listening_ports(_SS)
    assert len(lp.ports) == 1
    assert lp.ports[0].local_port == "22"


def test_empty_or_missing_output_returns_empty_not_crash() -> None:
    assert parse_ss_listening("").ports == []
    assert parse_netstat_listening("").ports == []
    assert parse_listening_ports("").ports == []
    # 命令缺失常见 stderr 混入 stdout 的杂讯行
    assert parse_listening_ports("bash: ss: command not found").ports == []
