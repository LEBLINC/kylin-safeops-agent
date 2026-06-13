"""沙箱测试（D，PR2b-v2）。

两层：
1. 纯函数层（所有平台都跑）：build_sandbox_argv / get_sandbox_profile 结构与映射。
2. 集成层（Linux + systemd only）：经真实 wrapper 脚本跑 systemd-run 瞬态 service，
   断言 readonly/limited_write 真在内核级拒绝 /etc 写入——本次架构闭环的核心证据。

集成层不 mock、不伪装 skip：仅在"非 Linux / 无 systemd-run / 无法以 root 拉起瞬态单元"
时 skip 并打印真实原因（含 systemd-run stderr）；测试体内直接断言，绝不吞断言失败。
"""

from __future__ import annotations

import os
import platform
import subprocess
import uuid
from pathlib import Path

import pytest

from backend.app.executor.command_templates import COMMAND_TEMPLATES
from backend.app.executor.sandbox import (
    SUDO_PATH,
    TOOL_SANDBOX_PROFILES,
    WRAPPER_PATH,
    build_sandbox_argv,
    get_sandbox_profile,
)

_INNER = ["/usr/bin/df", "-PB1"]


# ===== 纯函数层（所有平台）==================================================


def test_profile_none_returns_copy() -> None:
    """profile=none：原样返回 inner_argv 副本，不走 wrapper，不 mutate 入参。"""
    out = build_sandbox_argv(_INNER, "none")
    assert out == _INNER
    assert out is not _INNER


def test_readonly_without_sudo_structure() -> None:
    """readonly + 无 sudo：[wrapper, profile, --, *inner]。属性不在 argv（在 wrapper 内）。"""
    out = build_sandbox_argv(_INNER, "readonly")
    assert out == [WRAPPER_PATH, "readonly", "--", *_INNER]
    # 安全属性是 wrapper 唯一事实来源，绝不出现在 Python 构建的 argv 里
    assert not any(item.startswith("ProtectSystem") for item in out)
    assert "-p" not in out


def test_readonly_with_sudo_structure() -> None:
    """readonly + sudo：[sudo, --, wrapper, profile, --, *inner]。"""
    out = build_sandbox_argv(_INNER, "readonly", use_sudo=True)
    assert out == [SUDO_PATH, "--", WRAPPER_PATH, "readonly", "--", *_INNER]


def test_limited_write_structure() -> None:
    """limited_write：profile 段正确传给 wrapper。"""
    out = build_sandbox_argv(_INNER, "limited_write", use_sudo=True)
    assert out == [SUDO_PATH, "--", WRAPPER_PATH, "limited_write", "--", *_INNER]


def test_build_does_not_mutate_inner() -> None:
    """build_sandbox_argv 返回新列表，不修改原 inner_argv。"""
    inner = ["/usr/bin/ps", "aux"]
    snapshot = list(inner)
    build_sandbox_argv(inner, "readonly", use_sudo=True)
    assert inner == snapshot


def test_argv_no_shell_metachar() -> None:
    """每项 argv 都是独立字符串，无 shell 元字符（无字符串拼接）。"""
    out = build_sandbox_argv(_INNER, "readonly", use_sudo=True)
    for item in out:
        for mc in (";", "|", "&", "$(", "`", ">", "<"):
            assert mc not in item


def test_profile_mappings() -> None:
    assert get_sandbox_profile("disk.usage") == "readonly"
    assert get_sandbox_profile("log.compress_rotate") == "limited_write"
    assert get_sandbox_profile("service.restart") == "limited_write"
    assert get_sandbox_profile("system.info") == "none"


def test_unknown_tool_defaults_readonly() -> None:
    """未注册工具默认 readonly（fail-closed）。"""
    assert get_sandbox_profile("ghost.tool") == "readonly"


def test_all_templates_have_profile() -> None:
    """COMMAND_TEMPLATES 里每个工具都在 TOOL_SANDBOX_PROFILES 显式注册。"""
    for tool_name in COMMAND_TEMPLATES:
        assert tool_name in TOOL_SANDBOX_PROFILES, f"{tool_name} 缺 sandbox profile"


# ===== 集成层（Linux + systemd only）=======================================

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER_SRC = _REPO_ROOT / "deploy" / "sandbox" / "kylin-safeops-run.sh"
_SYSTEMD_RUN = "/usr/bin/systemd-run"


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _sudo_prefix() -> list[str]:
    return [] if _is_root() else [SUDO_PATH, "-n"]


def _integration_skip_reason() -> str:
    """空串=可真跑；否则=透明 skip 原因（含真实 systemd-run stderr）。"""
    if platform.system() != "Linux":
        return "not Linux"
    if not os.path.isfile(_SYSTEMD_RUN):
        return f"systemd-run not found at {_SYSTEMD_RUN}"
    if not _WRAPPER_SRC.is_file():
        return f"wrapper script not found at {_WRAPPER_SRC}"
    # 探测：能否以 root 拉起瞬态 service（非 scope）
    try:
        probe = subprocess.run(
            [
                *_sudo_prefix(),
                _SYSTEMD_RUN,
                "--collect",
                "--quiet",
                "--pipe",
                "--wait",
                "--",
                "/bin/true",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"systemd-run probe failed to launch: {exc!r}"
    if probe.returncode != 0:
        return (
            f"cannot launch systemd-run transient unit (rc={probe.returncode}); "
            f"stderr={probe.stderr.strip()!r}; "
            f"repro: {' '.join(_sudo_prefix())} {_SYSTEMD_RUN} "
            f"--collect --quiet --pipe --wait -- /bin/true"
        )
    return ""


_SKIP_REASON = _integration_skip_reason()
_integration = pytest.mark.skipif(bool(_SKIP_REASON), reason=_SKIP_REASON)


def _run_via_wrapper(profile: str, inner_cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """经真实 wrapper 脚本执行（systemd 瞬态 service），不依赖 wrapper 安装。"""
    return subprocess.run(
        [*_sudo_prefix(), "bash", str(_WRAPPER_SRC), profile, "--", *inner_cmd],
        capture_output=True,
        text=True,
        timeout=30,
    )


@_integration
def test_readonly_denies_write_to_etc() -> None:
    """readonly：ProtectSystem=strict + ReadOnlyPaths=/ → 写 /etc 被内核级拒绝。"""
    target = f"/etc/kylin-safeops-test-{uuid.uuid4().hex}"
    res = _run_via_wrapper("readonly", ["/usr/bin/touch", target])
    try:
        assert res.returncode != 0, f"readonly 竟允许写 /etc！stderr={res.stderr!r}"
        assert not os.path.exists(target), "readonly 下 /etc 文件竟真被创建"
    finally:
        if os.path.exists(target):
            subprocess.run([*_sudo_prefix(), "/usr/bin/rm", "-f", target], check=False)


@_integration
def test_limited_write_denies_write_to_etc() -> None:
    """limited_write：ProtectSystem=full → /etc 只读，写 /etc 被拒。"""
    target = f"/etc/kylin-safeops-test-{uuid.uuid4().hex}"
    res = _run_via_wrapper("limited_write", ["/usr/bin/touch", target])
    try:
        assert res.returncode != 0, f"limited_write 竟允许写 /etc！stderr={res.stderr!r}"
        assert not os.path.exists(target)
    finally:
        if os.path.exists(target):
            subprocess.run([*_sudo_prefix(), "/usr/bin/rm", "-f", target], check=False)


@_integration
def test_limited_write_allows_write_to_var_log() -> None:
    """limited_write：/var/log 等运行目录可写（与 readonly 区分）。"""
    target = f"/var/log/kylin-safeops-test-{uuid.uuid4().hex}"
    res = _run_via_wrapper("limited_write", ["/usr/bin/touch", target])
    try:
        assert res.returncode == 0, f"limited_write 竟不允许写 /var/log！stderr={res.stderr!r}"
    finally:
        subprocess.run([*_sudo_prefix(), "/usr/bin/rm", "-f", target], check=False)


@_integration
def test_readonly_denies_write_to_var_log() -> None:
    """readonly：ReadOnlyPaths=/ → 连 /var/log 也只读（与 limited_write 形成对照）。"""
    target = f"/var/log/kylin-safeops-test-{uuid.uuid4().hex}"
    res = _run_via_wrapper("readonly", ["/usr/bin/touch", target])
    try:
        assert res.returncode != 0, f"readonly 竟允许写 /var/log！stderr={res.stderr!r}"
        assert not os.path.exists(target)
    finally:
        if os.path.exists(target):
            subprocess.run([*_sudo_prefix(), "/usr/bin/rm", "-f", target], check=False)


@_integration
def test_stdout_pipe_works() -> None:
    """--pipe：wrapper 内 systemd-run 的 stdout 接回调用者，可被捕获。"""
    token = uuid.uuid4().hex
    res = _run_via_wrapper("readonly", ["/usr/bin/echo", token])
    assert res.returncode == 0, f"stderr={res.stderr!r}"
    assert token in res.stdout, f"stdout 未透传：{res.stdout!r}"


@_integration
def test_exit_code_passthrough() -> None:
    """--wait：inner 命令退出码被透传（方案 B 语义不破）。"""
    res = _run_via_wrapper("readonly", ["/bin/false"])
    assert res.returncode != 0, "false 的非零退出码未透传"
