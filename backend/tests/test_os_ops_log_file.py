"""D8 感知工具③测试：log.journal_query / log.large_log_scan / file.lsof_check。"""

from __future__ import annotations

from backend.app.mcp.schema_validator import validate_args
from mcp_servers.os_ops import all_specs
from mcp_servers.os_ops.parsers import (
    parse_journal_lines,
    parse_log_size_scan,
    parse_lsof_output,
)
from mcp_servers.os_ops.tools_file import FILE_LSOF_CHECK
from mcp_servers.os_ops.tools_log import LOG_JOURNAL_QUERY, LOG_LARGE_LOG_SCAN

_MB = 1024 * 1024


def test_specs_registered_and_risk() -> None:
    names = {s.name for s in all_specs()}
    assert {"log.journal_query", "log.large_log_scan", "file.lsof_check"} <= names
    assert LOG_JOURNAL_QUERY.risk == "R0"
    assert LOG_LARGE_LOG_SCAN.risk == "R1"
    assert FILE_LSOF_CHECK.risk == "R0"


# ---- journal schema 约束 --------------------------------------------------


def test_journal_schema_accepts_valid() -> None:
    args = {"unit": "sshd.service", "priority": "err", "since": "-1h", "lines": 200}
    assert validate_args(args, LOG_JOURNAL_QUERY.input_schema).ok


def test_journal_schema_rejects_bad_priority() -> None:
    assert not validate_args({"priority": "catastrophic"}, LOG_JOURNAL_QUERY.input_schema).ok


def test_journal_schema_rejects_injection_in_unit() -> None:
    # 分号/反引号等注入字符不匹配 unit pattern
    assert not validate_args({"unit": "a; rm -rf /"}, LOG_JOURNAL_QUERY.input_schema).ok


def test_journal_schema_rejects_bad_since() -> None:
    assert not validate_args({"since": "$(reboot)"}, LOG_JOURNAL_QUERY.input_schema).ok


def test_journal_schema_lines_bounds() -> None:
    assert not validate_args({"lines": 0}, LOG_JOURNAL_QUERY.input_schema).ok
    assert not validate_args({"lines": 99999}, LOG_JOURNAL_QUERY.input_schema).ok


def test_journal_schema_transport_enum() -> None:
    assert validate_args({"transport": "audit"}, LOG_JOURNAL_QUERY.input_schema).ok
    assert not validate_args({"transport": "smtp"}, LOG_JOURNAL_QUERY.input_schema).ok


# ---- large_log_scan / lsof schema ----------------------------------------


def test_large_log_scan_path_must_be_absolute() -> None:
    assert validate_args({"path": "/var/log"}, LOG_LARGE_LOG_SCAN.input_schema).ok
    assert not validate_args({"path": "var/log"}, LOG_LARGE_LOG_SCAN.input_schema).ok
    assert not validate_args({"path": "/var/../etc"}, LOG_LARGE_LOG_SCAN.input_schema).ok


def test_lsof_schema() -> None:
    assert validate_args({"path": "/var/log/x.log"}, FILE_LSOF_CHECK.input_schema).ok
    assert validate_args({"pid": 1234}, FILE_LSOF_CHECK.input_schema).ok
    assert not validate_args({"pid": 0}, FILE_LSOF_CHECK.input_schema).ok
    assert not validate_args({"foo": "bar"}, FILE_LSOF_CHECK.input_schema).ok


# ---- parsers --------------------------------------------------------------


def test_parse_journal_lines() -> None:
    raw = "Jan 01 sshd: accepted\n\nJan 01 sshd: failed\n"
    le = parse_journal_lines(raw, unit="sshd.service")
    assert le.entries == ["Jan 01 sshd: accepted", "Jan 01 sshd: failed"]
    assert le.unit == "sshd.service"


def test_parse_log_size_scan_filter_sort() -> None:
    raw = f"{2 * _MB}\t/var/log/a.log\n{500 * _MB}\t/var/log/big.log\n"
    ll = parse_log_size_scan(raw, min_size_bytes=10 * _MB)
    assert [f.path for f in ll.files] == ["/var/log/big.log"]


def test_parse_lsof_output() -> None:
    raw = (
        "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
        "nginx 1200 root 6u IPv4 12345 0t0 TCP *:http\n"
        "sshd 900 root 3u IPv4 678 0t0 TCP *:ssh\n"
    )
    res = parse_lsof_output(raw)
    assert len(res.entries) == 2
    assert res.entries[0].command == "nginx"
    assert res.entries[0].pid == 1200
    assert res.entries[0].name == "*:http"


def test_parse_lsof_skips_malformed() -> None:
    raw = "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\nshort\n"
    assert parse_lsof_output(raw).entries == []
