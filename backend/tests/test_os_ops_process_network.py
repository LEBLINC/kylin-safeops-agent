"""D7 感知工具②测试：process.list / network.ports。"""

from __future__ import annotations

from backend.app.mcp.schema_validator import validate_args
from mcp_servers.os_ops import all_specs
from mcp_servers.os_ops.parsers import parse_ps_output, parse_ss_listening
from mcp_servers.os_ops.tools_network import NETWORK_PORTS
from mcp_servers.os_ops.tools_process import PROCESS_LIST

_PS = (
    "USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND\n"
    "root 1 0.1 0.5 1000 2000 ? Ss 10:00 0:01 /sbin/init\n"
    "app 42 5.0 2.0 5000 8000 ? Sl 10:01 0:30 python server.py --port 8080\n"
)
_SS = (
    "Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
    'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=900,fd=3))\n'
    'tcp LISTEN 0 128 [::]:80 [::]:* users:(("nginx",pid=1200,fd=6))\n'
)


def test_specs_registered() -> None:
    names = {s.name for s in all_specs()}
    assert {"process.list", "network.ports"} <= names
    assert PROCESS_LIST.risk == "R0"
    assert NETWORK_PORTS.risk == "R0"


def test_process_list_schema() -> None:
    assert validate_args({"sort_by": "cpu", "top_n": 10}, PROCESS_LIST.input_schema).ok
    assert not validate_args({"sort_by": "disk"}, PROCESS_LIST.input_schema).ok  # enum
    assert not validate_args({"top_n": 0}, PROCESS_LIST.input_schema).ok  # minimum 1
    assert not validate_args({"x": 1}, PROCESS_LIST.input_schema).ok  # extra


def test_network_ports_schema_no_args() -> None:
    assert validate_args({}, NETWORK_PORTS.input_schema).ok
    assert not validate_args({"iface": "eth0"}, NETWORK_PORTS.input_schema).ok


def test_parse_ps_output_sort_cpu() -> None:
    pl = parse_ps_output(_PS, sort_by="cpu")
    assert [p.pid for p in pl.processes] == [42, 1]  # 5.0% > 0.1%
    assert pl.processes[0].command == "python server.py --port 8080"
    assert pl.processes[0].rss_kb == 8000


def test_parse_ps_output_sort_mem_and_topn() -> None:
    pl = parse_ps_output(_PS, sort_by="mem", top_n=1)
    assert len(pl.processes) == 1
    assert pl.processes[0].pid == 42  # 2.0% > 0.5%


def test_parse_ps_skips_malformed() -> None:
    bad = "USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND\nshort line\n"
    assert parse_ps_output(bad).processes == []


def test_parse_ss_listening() -> None:
    lp = parse_ss_listening(_SS)
    assert len(lp.ports) == 2
    ssh = lp.ports[0]
    assert ssh.protocol == "TCP"
    assert ssh.local_port == "22"
    assert "sshd" in ssh.process
    # IPv6 [::]:80 端口正确从右侧分割
    assert lp.ports[1].local_port == "80"
