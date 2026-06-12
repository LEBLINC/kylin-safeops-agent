"""Executor 首版测试（D）。

Windows 上无法真跑 Linux 命令，用 mock 验证：
- 模板白名单拦截
- 无 shell
- '..' 路径拦截
- 截断
- 方案 B 失败语义
- fallback 探测
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.contracts.intent import CandidateTool
from backend.app.executor import PrivilegeExecutor, has_tool


def _tool(name: str, args: dict | None = None) -> CandidateTool:
    return CandidateTool(name=name, args=args or {})


# ---- 模板白名单 -----------------------------------------------------------


def test_all_os_ops_tools_have_template() -> None:
    """os_ops 已注册的工具都应有命令模板。"""
    from mcp_servers.os_ops import all_specs

    for spec in all_specs():
        # config.diff 暂无直接模板（需基线对比，非单命令），跳过
        if spec.name == "config.diff":
            continue
        assert has_tool(spec.name), f"missing template for {spec.name}"


def test_unknown_tool_returns_127() -> None:
    ex = PrivilegeExecutor()
    result = asyncio.run(ex.execute(_tool("ghost.tool")))
    assert result.exit_code == 127
    assert "tool-not-in-whitelist" in result.stdout_truncated
    assert result.is_untrusted is True


# ---- 路径安全 --------------------------------------------------------------


def test_dotdot_path_blocked() -> None:
    """路径含 '..' → 方案 B 非 0 return，不 raise。"""
    ex = PrivilegeExecutor()
    result = asyncio.run(ex.execute(_tool("disk.large_files", {"path": "/var/../etc"})))
    assert result.exit_code != 0
    assert ".." in result.stdout_truncated
    assert result.is_untrusted is True


# ---- 方案 B 失败语义 -------------------------------------------------------


def test_command_not_found_returns_127_not_raise() -> None:
    """命令不存在 → exit_code=127，不抛异常。"""
    ex = PrivilegeExecutor()
    with patch("shutil.which", return_value=None):
        result = asyncio.run(ex.execute(_tool("network.ports")))
    assert result.exit_code == 127
    assert "command-not-available" in result.stdout_truncated


def test_command_nonzero_exit_returns_normally() -> None:
    """命令非 0 退出 → 正常 return（方案 B），exit_code 反映真实值。"""
    ex = PrivilegeExecutor()

    async def mock_exec() -> None:
        pass

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"error output", b"some stderr"))
    mock_proc.returncode = 2

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = asyncio.run(ex.execute(_tool("disk.usage")))

    assert result.exit_code == 2
    assert result.is_untrusted is True
    assert "error output" in result.stdout_truncated
    assert "--- stderr ---" in result.stdout_truncated


# ---- stdout 截断 -----------------------------------------------------------


def test_stdout_truncated_at_8kb() -> None:
    ex = PrivilegeExecutor()
    big_output = b"x" * (8 * 1024 + 500)

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(big_output, b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = asyncio.run(ex.execute(_tool("disk.usage")))

    assert "truncated" in result.stdout_truncated
    assert result.exit_code == 0


# ---- stderr 追加 -----------------------------------------------------------


def test_stderr_appended() -> None:
    ex = PrivilegeExecutor()
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"normal output", b"warning msg"))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = asyncio.run(ex.execute(_tool("process.list")))

    assert "--- stderr ---" in result.stdout_truncated
    assert "warning msg" in result.stdout_truncated


# ---- 不使用 shell -----------------------------------------------------------


def test_no_shell_in_subprocess() -> None:
    """确认 create_subprocess_exec 被调用（不是 create_subprocess_shell）。"""
    ex = PrivilegeExecutor()
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        asyncio.run(ex.execute(_tool("disk.usage")))
    mock_exec.assert_called_once()
    # 确认第一个参数是命令路径，不是 shell 字符串
    call_args = mock_exec.call_args
    assert call_args[0][0] == "/usr/bin/df"


# ---- fallback 探测 ----------------------------------------------------------


def test_fallback_uses_netstat_when_ss_missing() -> None:
    """ss 不存在时回退到 netstat。"""
    ex = PrivilegeExecutor()

    def which_side_effect(cmd: str) -> str | None:
        return "/usr/bin/netstat" if cmd == "netstat" else None

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"netstat output", b""))
    mock_proc.returncode = 0

    with (
        patch("shutil.which", side_effect=which_side_effect),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec,
    ):
        result = asyncio.run(ex.execute(_tool("network.ports")))

    assert result.exit_code == 0
    call_args = mock_exec.call_args
    assert "/usr/bin/netstat" in call_args[0]


# ---- is_untrusted 默认 True -------------------------------------------------


def test_result_always_untrusted() -> None:
    ex = PrivilegeExecutor()
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"safe?", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = asyncio.run(ex.execute(_tool("disk.usage")))

    assert result.is_untrusted is True


# ---- symlink / TOCTOU 兜底（D-1e）----------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="symlink 测试需 Linux 环境")
def test_sanitize_arg_resolves_symlink_to_realpath() -> None:
    """_sanitize_arg 在 Linux 上通过 os.path.realpath 将 symlink 解析为真实路径。

    防御分层（职责边界）：
    - PolicyEngine：词法路径裁决（无 IO，确定性）。
    - Executor：realpath 解析 symlink；若真实目标 != 词法路径，对真实目标重跑
      保护路径 + deny 规则校验（real_path_violation），命中即拒绝执行。
    /etc 对只读工具不在拒绝面（与策略层对词法路径 /etc 的裁决一致），故放行并返回真实路径。
    """
    ex = PrivilegeExecutor()
    with (
        patch("os.path.realpath", return_value="/etc"),
        patch("platform.system", return_value="Linux"),
    ):
        resolved = ex._sanitize_arg("/tmp/link_to_etc", "disk.large_files")

    assert resolved == "/etc", "symlink 应被解析为真实路径 /etc"


@pytest.mark.skipif(sys.platform == "win32", reason="symlink 测试需 Linux 环境")
def test_sanitize_arg_dotdot_after_realpath_blocked() -> None:
    """realpath 解析后若结果含 '..'（极端情况）→ _PathTraversalError（方案 B 上游拦截）。

    二次 has_dotdot 守卫（privilege_executor.py _sanitize_arg 第二层检查）防御
    边缘情况：realpath 本身正常不返回 '..'，此处测试守卫逻辑在异常输入下生效。
    """
    from backend.app.executor.privilege_executor import _PathTraversalError

    ex = PrivilegeExecutor()
    with (
        patch("os.path.realpath", return_value="/var/../etc"),
        patch("platform.system", return_value="Linux"),
    ):
        with pytest.raises(_PathTraversalError):
            ex._sanitize_arg("/tmp/weird_link", "disk.large_files")


@pytest.mark.skipif(sys.platform == "win32", reason="symlink 测试需 Linux 环境")
def test_sanitize_arg_symlink_to_protected_file_blocked() -> None:
    """symlink 解析到受保护文件（/etc/shadow，FILE001）→ _PathTraversalError 拒绝。"""
    from backend.app.executor.privilege_executor import _PathTraversalError

    ex = PrivilegeExecutor()
    with (
        patch("os.path.realpath", return_value="/etc/shadow"),
        patch("platform.system", return_value="Linux"),
    ):
        with pytest.raises(_PathTraversalError, match="FILE001"):
            ex._sanitize_arg("/tmp/evil_link", "disk.large_files")


@pytest.mark.skipif(sys.platform == "win32", reason="symlink 测试需 Linux 环境")
def test_real_executor_symlink_escape_guarded(tmp_path) -> None:
    """真 symlink（无 mock 解析）：/tmp 下链接指向 /etc/shadow → 执行被拦。

    策略层对词法路径（tmp 下的链接）裁决 allow；Executor 在执行时 realpath 发现
    真实目标是 /etc/shadow（FILE001 deny 面），必须拒绝且不得起任何子进程。
    """
    link = tmp_path / "evil"
    link.symlink_to("/etc/shadow")

    ex = PrivilegeExecutor()
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        result = asyncio.run(ex.execute(_tool("disk.large_files", {"path": str(link)})))

    mock_exec.assert_not_called()
    assert result.exit_code != 0
    assert "FILE001" in result.stdout_truncated
    assert result.is_untrusted is True


@pytest.mark.skipif(sys.platform == "win32", reason="symlink 测试需 Linux 环境")
def test_real_executor_toctou_not_exploitable(tmp_path) -> None:
    """TOCTOU：评估时是普通目录，执行前被换成指向 /home（confirm_required）的 symlink → 拦。

    Executor 在执行时刻（而非评估时刻）做 realpath + 真实路径校验，
    评估与执行之间的偷换不可利用（真实目标命中 PATH_CONFIRM_REQUIRED 即拒绝：
    审批针对的是评估时的词法路径，不能迁移到策略层从未见过的目标）。
    """
    from backend.app.mcp.registry import ToolRegistry
    from backend.app.security.guard import RuleBasedPolicyEngine
    from mcp_servers.os_ops import all_specs

    target = tmp_path / "scan_me"
    target.mkdir()

    # 评估时刻：词法路径是普通目录，策略层 allow
    engine = RuleBasedPolicyEngine(registry=ToolRegistry(all_specs()))
    verdict = engine.evaluate(_tool("disk.large_files", {"path": str(target)}))
    assert verdict.decision == "allow"

    # 执行前偷换：同一路径变成指向 confirm_required 保护目录的 symlink
    target.rmdir()
    target.symlink_to("/home")

    ex = PrivilegeExecutor()
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        result = asyncio.run(ex.execute(_tool("disk.large_files", {"path": str(target)})))

    mock_exec.assert_not_called()
    assert result.exit_code != 0
    assert "PATH_CONFIRM_REQUIRED" in result.stdout_truncated
    assert result.is_untrusted is True


# ---- 端到端策略拦截哨兵（D-1d）-------------------------------------------


def test_e2e_policy_deny_before_executor() -> None:
    """端到端哨兵：FILE001 deny 工具经完整策略层被拦，Executor 不执行任何命令。

    验证命题：'LLM 建议访问 /etc/shadow → PolicyEngine deny → Executor 不被调用'。
    当前在策略层验证 evaluate 返回 deny；Executor 执行层验证通过 calls==[] 侧证。

    NOTE(D-1d-UPGRADE): PR2 合入 L 接线后，此测试需追加：
      - FakeExecutor 换真 PrivilegeExecutor，确认危险命令未被真实执行
      - 真实 ToolResult.exit_code != 0，stdout 经结果闸密封
    """
    from backend.app.contracts.intent import CandidateTool as CT
    from backend.app.mcp.registry import ToolRegistry
    from backend.app.security.guard import RuleBasedPolicyEngine
    from mcp_servers.os_ops import all_specs  # 项目内模块，永远可用，与 L-2 对齐

    registry = ToolRegistry(all_specs())

    engine = RuleBasedPolicyEngine(registry=registry)
    candidate = CT(name="disk.large_files", args={"path": "/etc/shadow"})
    verdict = engine.evaluate(candidate)

    # FILE001 + PATH_FORBID_MODIFY（/etc 前缀 + disk.large_files 是只读工具，
    # 此处 FILE001 正则 /etc/(shadow|passwd) 命中）
    assert verdict.decision == "deny", f"FILE001 应拦截 /etc/shadow，实际: {verdict}"
    assert "FILE001" in verdict.matched_rules
    assert verdict.approval_required is False
    assert verdict.final_risk == "R4"
