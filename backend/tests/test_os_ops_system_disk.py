"""D6 感知工具①测试：system.info / disk.usage / disk.large_files。

测 ToolSpec 合法性 + 纯解析器 + 与 gateway 三道闸的集成（schema 校验）。
不跑真命令：解析器吃样例 stdout。
"""

from __future__ import annotations

from backend.app.contracts.intent import CandidateTool
from backend.app.mcp.schema_validator import validate_args
from mcp_servers.os_ops import all_specs
from mcp_servers.os_ops.parsers import (
    parse_df_output,
    parse_find_size_output,
    parse_os_release,
    parse_system_info,
)
from mcp_servers.os_ops.tools_disk import DISK_LARGE_FILES, DISK_USAGE
from mcp_servers.os_ops.tools_system import SYSTEM_INFO

_MB = 1024 * 1024


# ---- ToolSpec 合法性 ------------------------------------------------------


def test_all_specs_names_unique_and_expected() -> None:
    names = [s.name for s in all_specs()]
    assert len(names) == len(set(names))  # 无重名
    # D6 工具①必须在内（后续增量会加更多，故用子集断言而非相等）
    assert {"system.info", "disk.usage", "disk.large_files"} <= set(names)


def test_specs_risk_levels() -> None:
    assert SYSTEM_INFO.risk == "R0"
    assert DISK_USAGE.risk == "R0"
    assert DISK_LARGE_FILES.risk == "R1"  # 文件系统扫描，开销较大


# ---- schema 与 gateway 闸2 集成 ------------------------------------------


def test_large_files_schema_accepts_valid_args() -> None:
    res = validate_args(
        {"path": "/var/log", "min_size_mb": 100, "top_n": 20}, DISK_LARGE_FILES.input_schema
    )
    assert res.ok


def test_large_files_schema_rejects_relative_path() -> None:
    res = validate_args({"path": "var/log"}, DISK_LARGE_FILES.input_schema)
    assert not res.ok  # pattern ^/ 不匹配


def test_large_files_schema_rejects_dotdot() -> None:
    res = validate_args({"path": "/var/../etc"}, DISK_LARGE_FILES.input_schema)
    assert not res.ok  # schema_validator 拦 ..


def test_large_files_schema_rejects_extra_field() -> None:
    res = validate_args({"path": "/x", "cmd": "rm -rf /"}, DISK_LARGE_FILES.input_schema)
    assert not res.ok


def test_system_info_schema_rejects_any_arg() -> None:
    assert validate_args({}, SYSTEM_INFO.input_schema).ok
    assert not validate_args({"host": "x"}, SYSTEM_INFO.input_schema).ok


# ---- 解析器 ---------------------------------------------------------------


def test_parse_os_release() -> None:
    raw = 'PRETTY_NAME="Kylin V11"\nVERSION_ID="11"\nID=kylin\n'
    d = parse_os_release(raw)
    assert d["PRETTY_NAME"] == "Kylin V11"
    assert d["VERSION_ID"] == "11"


def test_parse_system_info() -> None:
    info = parse_system_info(
        {
            "hostname": "node1\n",
            "os_release": 'PRETTY_NAME="Kylin V11"\nVERSION_ID="11"\n',
            "kernel": "5.10.0\n",
            "arch": "loongarch64\n",
            "uptime": "up 3 days\n",
        }
    )
    assert info.hostname == "node1"
    assert info.os_name == "Kylin V11"
    assert info.os_version == "11"
    assert info.arch == "loongarch64"


def test_parse_df_output() -> None:
    raw = (
        "Filesystem 1B-blocks Used Available Capacity Mounted on\n"
        "/dev/sda1 1000 230 770 23% /\n"
        "tmpfs 500 0 500 0% /dev/shm\n"
    )
    du = parse_df_output(raw)
    assert len(du.filesystems) == 2
    root = du.filesystems[0]
    assert root.filesystem == "/dev/sda1"
    assert root.size_bytes == 1000
    assert root.use_percent == 23
    assert root.mount_point == "/"


def test_parse_df_skips_malformed_lines() -> None:
    raw = (
        "Filesystem 1B-blocks Used Available Capacity Mounted on\n"
        "garbage line\n"
        "/dev/sda1 100 1 99 1% /\n"
    )
    du = parse_df_output(raw)
    assert len(du.filesystems) == 1


def test_parse_find_size_filter_sort_topn() -> None:
    raw = (
        f"{5 * _MB}\t/var/log/a.log\n{200 * _MB}\t/var/log/big.log\n{1 * _MB}\t/var/log/small.log\n"
    )
    lf = parse_find_size_output(raw, min_size_bytes=10 * _MB, top_n=5)
    # 仅 >=10MB：big.log 留下，a.log/small.log 滤掉
    assert [f.path for f in lf.files] == ["/var/log/big.log"]


def test_parse_find_size_sorts_descending() -> None:
    raw = f"{1 * _MB}\t/a\n{3 * _MB}\t/b\n{2 * _MB}\t/c\n"
    lf = parse_find_size_output(raw)
    assert [f.size_bytes for f in lf.files] == [3 * _MB, 2 * _MB, 1 * _MB]


def test_parse_find_size_skips_permission_error_lines() -> None:
    raw = f"{2 * _MB}\t/ok\nfind: '/root': Permission denied\n"
    lf = parse_find_size_output(raw)
    assert [f.path for f in lf.files] == ["/ok"]


# ---- 端到端：os_ops specs 可被 gateway 注册并通过结构校验 ------------------


def test_specs_registrable_and_callable_shape() -> None:
    from backend.app.mcp.registry import ToolRegistry

    reg = ToolRegistry(all_specs())
    assert reg.has("disk.large_files")
    # 模拟 LLM 提的合法调用经结构校验
    tool = CandidateTool(name="disk.large_files", args={"path": "/var/log", "min_size_mb": 500})
    spec = reg.get(tool.name)
    assert spec is not None
    assert validate_args(tool.args, spec.input_schema).ok
