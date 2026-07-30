"""沙箱启用接线 — build_gateway 按平台 + env 传 sandbox_enabled（默认关）。

覆盖（不真跑沙箱；真验证在麒麟 VM 由 verify-sandbox-on-vm.sh 做）：
- 默认（无 env）：executor.sandbox_enabled is False（零回归证据）。
- Linux + KYLIN_SANDBOX_ENABLED=1 → True（启用证据）。
- Windows + env=1 → False（平台护栏证据）。
- env 非 "1"（"0"/"true"/空）→ False（仅显式 "1" 才开）；前后空白被 strip。

L 仅接"开关"：读 env 传 PrivilegeExecutor(sandbox_enabled=...)，不碰 executor/sandbox 实现。
"""

from __future__ import annotations

import platform

import pytest

from backend.app.api import _fakes
from backend.app.api._fakes import build_gateway


def _sandbox_flag_of(gateway: object) -> bool:
    """从 build_gateway 装配的 gateway 取注入执行器的 sandbox 开关。"""
    return gateway._executor._sandbox_enabled  # type: ignore[attr-defined]


def test_default_sandbox_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 env → 沙箱关（零行为改变、现有测试零回归的依据）。"""
    monkeypatch.delenv("KYLIN_SANDBOX_ENABLED", raising=False)
    assert _sandbox_flag_of(build_gateway()) is False


def test_enabled_on_linux_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux + KYLIN_SANDBOX_ENABLED=1 → 沙箱开。"""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setenv("KYLIN_SANDBOX_ENABLED", "1")
    assert _sandbox_flag_of(build_gateway()) is True


def test_disabled_on_windows_even_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows + env=1 → 仍关（平台护栏：Windows 跑不了 systemd 瞬态 service）。"""
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setenv("KYLIN_SANDBOX_ENABLED", "1")
    assert _sandbox_flag_of(build_gateway()) is False


def test_env_must_be_exactly_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux 下 env 非 '1'（'0'/'true'/空）→ 关；仅显式 '1' 才开。"""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    for val in ("0", "true", "yes", ""):
        monkeypatch.setenv("KYLIN_SANDBOX_ENABLED", val)
        assert _sandbox_flag_of(build_gateway()) is False, f"env={val!r} 不应启用"


def test_env_whitespace_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """前后空白被 strip：' 1 ' 在 Linux 下仍启用。"""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setenv("KYLIN_SANDBOX_ENABLED", " 1 ")
    assert _sandbox_flag_of(build_gateway()) is True


def test_sandbox_env_const_name() -> None:
    """守护 env 开关名不漂移（部署文档/systemd unit 依赖此名）。"""
    assert _fakes._SANDBOX_ENV == "KYLIN_SANDBOX_ENABLED"
