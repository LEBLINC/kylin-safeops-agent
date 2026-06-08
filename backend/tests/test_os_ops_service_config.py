"""D9 感知工具④测试：service.status / config.hash_snapshot / config.diff。"""

from __future__ import annotations

from backend.app.mcp.schema_validator import validate_args
from mcp_servers.os_ops import all_specs
from mcp_servers.os_ops.models import ConfigSnapshot
from mcp_servers.os_ops.parsers import (
    diff_config_snapshots,
    parse_sha256sum_output,
    parse_systemctl_show,
)
from mcp_servers.os_ops.tools_config import CONFIG_DIFF, CONFIG_HASH_SNAPSHOT
from mcp_servers.os_ops.tools_service import SERVICE_STATUS

_H1 = "a" * 64
_H2 = "b" * 64


def test_specs_registered_and_risk() -> None:
    names = {s.name for s in all_specs()}
    assert {"service.status", "config.hash_snapshot", "config.diff"} <= names
    for spec in (SERVICE_STATUS, CONFIG_HASH_SNAPSHOT, CONFIG_DIFF):
        assert spec.risk == "R0"


# ---- schema --------------------------------------------------------------


def test_service_status_schema() -> None:
    assert validate_args({"service_name": "sshd.service"}, SERVICE_STATUS.input_schema).ok
    assert not validate_args({"service_name": "a; reboot"}, SERVICE_STATUS.input_schema).ok
    assert not validate_args({}, SERVICE_STATUS.input_schema).ok  # required


def test_config_snapshot_schema_paths_absolute() -> None:
    assert validate_args({"paths": ["/etc/ssh/sshd_config"]}, CONFIG_HASH_SNAPSHOT.input_schema).ok
    assert not validate_args({"paths": ["etc/x"]}, CONFIG_HASH_SNAPSHOT.input_schema).ok  # ^/
    assert not validate_args({"paths": []}, CONFIG_HASH_SNAPSHOT.input_schema).ok  # minItems
    assert not validate_args({"paths": ["/x/../y"]}, CONFIG_HASH_SNAPSHOT.input_schema).ok  # ..


def test_config_diff_schema_optional_baseline() -> None:
    assert validate_args({"paths": ["/etc/hosts"]}, CONFIG_DIFF.input_schema).ok
    assert validate_args(
        {"paths": ["/etc/hosts"], "baseline_id": "b-2026"}, CONFIG_DIFF.input_schema
    ).ok
    assert not validate_args({"paths": ["/etc/hosts"], "x": 1}, CONFIG_DIFF.input_schema).ok


# ---- parsers --------------------------------------------------------------


def test_parse_systemctl_show() -> None:
    raw = (
        "Id=sshd.service\n"
        "LoadState=loaded\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "UnitFileState=enabled\n"
        "MainPID=900\n"
        "Description=OpenSSH server daemon\n"
    )
    st = parse_systemctl_show(raw, name="sshd.service")
    assert st.active_state == "active"
    assert st.sub_state == "running"
    assert st.main_pid == 900
    assert st.unit_file_state == "enabled"


def test_parse_systemctl_show_bad_pid_defaults_zero() -> None:
    st = parse_systemctl_show("MainPID=notanint\n", name="x")
    assert st.main_pid == 0


def test_parse_sha256sum_output() -> None:
    raw = f"{_H1}  /etc/ssh/sshd_config\n{_H2}  /etc/hosts\n"
    snap = parse_sha256sum_output(raw)
    assert snap.hashes == {"/etc/ssh/sshd_config": _H1, "/etc/hosts": _H2}


def test_parse_sha256sum_skips_malformed() -> None:
    raw = f"{_H1}  /etc/ok\nnotahash  /etc/bad\nshort\n"
    snap = parse_sha256sum_output(raw)
    assert snap.hashes == {"/etc/ok": _H1}


def test_diff_config_snapshots() -> None:
    old = ConfigSnapshot(hashes={"/a": _H1, "/b": _H1, "/c": _H1})
    new = ConfigSnapshot(hashes={"/b": _H1, "/c": _H2, "/d": _H1})
    diff = diff_config_snapshots(old, new)
    assert diff.added == ["/d"]
    assert diff.removed == ["/a"]
    assert diff.changed == ["/c"]


def test_diff_config_snapshots_no_change() -> None:
    snap = ConfigSnapshot(hashes={"/a": _H1})
    diff = diff_config_snapshots(snap, snap)
    assert diff.added == [] and diff.removed == [] and diff.changed == []
