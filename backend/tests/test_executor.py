"""Executor 首版测试。

Windows 上无法真跑 Linux 命令，用 mock 验证：
- 模板白名单拦截
- 无 shell
- '..' 路径拦截
- 截断（H7：流式 capped 读取，非全量进内存）
- 方案 B 失败语义
- fallback 探测
- 超时 kill + 回收子进程（H7 孤儿泄漏）
- 大输出内存有界（H7 内存 DoS）

H7 起 _run_subprocess 不再走 proc.communicate()，改为并发 drain 两管道
（proc.stdout.read / proc.stderr.read）+ proc.wait()。故 mock 子进程用 _make_proc
提供真实 StreamReader 语义的 .stdout/.stderr（_FakeStream），而非 communicate 罐头。
system.info（_execute_system_info）仍用 communicate，其用例保留 communicate mock。
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tracemalloc
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.contracts.intent import CandidateTool
from backend.app.executor import PrivilegeExecutor, has_tool
from backend.app.executor.privilege_executor import MAX_OUTPUT_BYTES


def _tool(name: str, args: dict | None = None) -> CandidateTool:
    return CandidateTool(name=name, args=args or {})


# ---- H7 流式子进程替身 ------------------------------------------------------


class _FakeStream:
    """模拟 asyncio.StreamReader：分块吐出预置字节，读尽返回 b""（EOF）。"""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    async def read(self, n: int) -> bytes:
        if self._pos >= len(self._data):
            return b""
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk


class _ChunkStream:
    """按需产出固定 chunk count 次，不在内存持有全量（用于大输出内存断言）。

    每次 read 返回同一个 chunk 对象（零新分配），count 次后 EOF——喂 N*len(chunk)
    字节给 executor，但产生侧内存恒为 len(chunk)，从而 tracemalloc 峰值只反映
    executor 侧是否 capped。
    """

    def __init__(self, chunk: bytes, count: int) -> None:
        self._chunk = chunk
        self._remaining = count

    async def read(self, n: int) -> bytes:
        if self._remaining <= 0:
            return b""
        self._remaining -= 1
        return self._chunk


def _make_proc(*, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> MagicMock:
    """构造 H7 流式消费路径的子进程替身（.stdout/.stderr 为 _FakeStream，.wait 异步）。"""
    proc = MagicMock()
    proc.stdout = _FakeStream(stdout)
    proc.stderr = _FakeStream(stderr)
    proc.returncode = returncode
    proc.wait = AsyncMock(return_value=returncode)
    proc.kill = MagicMock()
    return proc


def _make_hanging_proc(*, returncode: int = 0) -> MagicMock:
    """构造一个 drain 永不结束的子进程替身（read 挂起），驱动 wait_for 超时路径。"""
    proc = MagicMock()

    async def _hang(_n: int) -> bytes:
        await asyncio.sleep(10)
        return b""

    proc.stdout = MagicMock()
    proc.stdout.read = _hang
    proc.stderr = MagicMock()
    proc.stderr.read = _hang
    proc.returncode = returncode
    proc.wait = AsyncMock(return_value=returncode)
    proc.kill = MagicMock()
    return proc


# ---- 模板白名单 -----------------------------------------------------------


def test_all_os_ops_tools_have_template() -> None:
    """os_ops 已注册的工具都应有命令模板。"""
    from mcp_servers.os_ops import all_specs

    for spec in all_specs():
        # config.diff 暂无直接模板（需基线对比，非单命令），跳过
        if spec.name == "config.diff":
            continue
        assert has_tool(spec.name), f"missing template for {spec.name}"


def test_resource_tool_templates_registered() -> None:
    """阶段 2B：cpu/mem 资源工具模板已注册（休眠态，待接 ToolSpec 激活）。"""
    assert has_tool("system.cpu_load")
    assert has_tool("system.mem_usage")


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
    mock_proc = _make_proc(stdout=b"error output", stderr=b"some stderr", returncode=2)

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
    mock_proc = _make_proc(stdout=big_output, returncode=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = asyncio.run(ex.execute(_tool("disk.usage")))

    assert "truncated" in result.stdout_truncated
    assert "500 bytes" in result.stdout_truncated
    assert result.exit_code == 0


# ---- stderr 追加 -----------------------------------------------------------


def test_stderr_appended() -> None:
    ex = PrivilegeExecutor()
    mock_proc = _make_proc(stdout=b"normal output", stderr=b"warning msg", returncode=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = asyncio.run(ex.execute(_tool("process.list")))

    assert "--- stderr ---" in result.stdout_truncated
    assert "warning msg" in result.stdout_truncated


# ---- 不使用 shell -----------------------------------------------------------


def test_no_shell_in_subprocess() -> None:
    """确认 create_subprocess_exec 被调用（不是 create_subprocess_shell）。"""
    ex = PrivilegeExecutor()
    mock_proc = _make_proc(stdout=b"ok", returncode=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        asyncio.run(ex.execute(_tool("disk.usage")))
    mock_exec.assert_called_once()
    # 确认第一个参数是命令路径，不是 shell 字符串
    call_args = mock_exec.call_args
    assert call_args[0][0] == "/usr/bin/df"


def test_log_compress_rotate_appends_path() -> None:
    """log.compress_rotate 必须把 path 拼进 argv，否则 gzip 无文件参数会读 stdin 卡死。"""
    ex = PrivilegeExecutor()
    mock_proc = _make_proc(stdout=b"", returncode=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        asyncio.run(ex.execute(_tool("log.compress_rotate", {"path": "/var/log/app.log"})))

    call_args = mock_exec.call_args[0]
    assert call_args[0] == "/usr/bin/gzip"
    assert "/var/log/app.log" in call_args


# ---- fallback 探测 ----------------------------------------------------------


def test_fallback_uses_netstat_when_ss_missing() -> None:
    """ss 不存在时回退到 netstat。"""
    ex = PrivilegeExecutor()

    def which_side_effect(cmd: str) -> str | None:
        return "/usr/bin/netstat" if cmd == "netstat" else None

    mock_proc = _make_proc(stdout=b"netstat output", returncode=0)

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
    mock_proc = _make_proc(stdout=b"safe?", returncode=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = asyncio.run(ex.execute(_tool("disk.usage")))

    assert result.is_untrusted is True


# ---- H7 流式 capped 读取（内存 DoS 防护）---------------------------------


def test_read_capped_retains_head_counts_overflow() -> None:
    """_read_capped：内存只留前 MAX_OUTPUT_BYTES，其余边读边丢并精确计数。"""
    stream = _FakeStream(b"a" * (MAX_OUTPUT_BYTES + 1234))
    head, overflow = asyncio.run(PrivilegeExecutor._read_capped(stream))
    assert len(head) == MAX_OUTPUT_BYTES
    assert overflow == 1234


def test_read_capped_none_stream() -> None:
    """_read_capped(None)（管道缺失）→ 空头部 + 零溢出，不抛。"""
    head, overflow = asyncio.run(PrivilegeExecutor._read_capped(None))
    assert head == b""
    assert overflow == 0


def test_large_output_not_loaded_into_memory() -> None:
    """喂 64MB stdout，executor 只保留 8KB 头部——tracemalloc 峰值必须远小于 64MB。

    坐实 H7 内存 DoS 修复：若仍是 communicate 全量读进内存，峰值 ≥ 64MB；capped 后
    峰值应 < 8MB（8 倍安全余量，覆盖 asyncio/解释器开销）。
    """
    chunk = b"y" * (64 * 1024)  # 64KB/次
    total_chunks = 1024  # 64MB 总量
    ex = PrivilegeExecutor()

    proc = MagicMock()
    proc.stdout = _ChunkStream(chunk, total_chunks)
    proc.stderr = _FakeStream(b"")
    proc.returncode = 0
    proc.wait = AsyncMock(return_value=0)
    proc.kill = MagicMock()

    tracemalloc.start()
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = asyncio.run(ex.execute(_tool("disk.usage")))
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert "truncated" in result.stdout_truncated
    assert peak < 8 * 1024 * 1024, f"峰值 {peak} 字节——疑似全量进内存（未 capped）"


def test_large_stderr_capped() -> None:
    """大 stderr 同样 capped 到 8KB 头部（原 communicate 版 stderr 无上限，H7 收紧）。"""
    ex = PrivilegeExecutor()
    big_stderr = b"e" * (MAX_OUTPUT_BYTES + 50_000)
    mock_proc = _make_proc(stdout=b"out", stderr=big_stderr, returncode=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = asyncio.run(ex.execute(_tool("disk.usage")))

    # stderr 段 = "--- stderr ---\n" + 至多 8KB 头部；整体远小于 50KB+
    assert "--- stderr ---" in result.stdout_truncated
    stderr_seg = result.stdout_truncated.split("--- stderr ---\n", 1)[1]
    assert len(stderr_seg.encode("utf-8")) <= MAX_OUTPUT_BYTES


# ---- H7 超时 kill + 回收子进程（孤儿泄漏防护）---------------------------


def test_timeout_kills_and_reaps_child() -> None:
    """drain 超时 → 返回 124 + proc.kill() 被调 + proc.wait() 被 await（回收僵尸）。"""
    ex = PrivilegeExecutor()
    ex._timeout = 0.05  # 快速触发 wait_for 超时，不真等 30s
    proc = _make_hanging_proc(returncode=-9)

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = asyncio.run(ex.execute(_tool("disk.usage")))

    assert result.exit_code == 124
    assert "timeout" in result.stdout_truncated
    proc.kill.assert_called_once()
    proc.wait.assert_awaited()  # 必须回收，否则孤儿泄漏


def test_timeout_kill_exception_swallowed() -> None:
    """kill() 抛异常（进程已退出等）时兜住，仍返回 124 且继续回收。"""
    ex = PrivilegeExecutor()
    ex._timeout = 0.05
    proc = _make_hanging_proc(returncode=-9)
    proc.kill = MagicMock(side_effect=ProcessLookupError())

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = asyncio.run(ex.execute(_tool("disk.usage")))

    assert result.exit_code == 124  # kill 抛异常不影响方案 B 语义
    proc.wait.assert_awaited()  # kill 抛了仍尝试回收


def test_kill_reap_survives_unreapable_child() -> None:
    """回收 wait() 也挂死（D 态进程）时，_kill_and_reap 由二级 wait_for 兜底不永久挂起。"""
    proc = MagicMock()
    proc.kill = MagicMock()

    async def _never() -> None:
        await asyncio.sleep(10)

    proc.wait = _never

    with patch("backend.app.executor.privilege_executor.KILL_REAP_TIMEOUT", 0.05):
        # 不抛、不挂：二级 wait_for 超时后放弃等待
        asyncio.run(PrivilegeExecutor._kill_and_reap(proc))
    proc.kill.assert_called_once()


def test_kill_reap_none_proc_noop() -> None:
    """_kill_and_reap(None)（子进程从未起）→ 无操作不抛。"""
    asyncio.run(PrivilegeExecutor._kill_and_reap(None))


# ---- O-H7-1 FD 卫生：kill 后 / 正常完成后显式关 transport --------------------


def test_close_transport_releases_fd() -> None:
    """_close_transport 显式调 proc._transport.close()（FD 立即归还池不等 GC）。"""
    proc = MagicMock()
    transport = MagicMock()
    proc._transport = transport

    PrivilegeExecutor._close_transport(proc)

    transport.close.assert_called_once()


def test_close_transport_none_proc_and_no_transport_noop() -> None:
    """_close_transport(None) 与 proc 无 _transport 属性 → 无操作不抛（幂等/防御）。"""
    # None proc
    PrivilegeExecutor._close_transport(None)
    # proc 存在但 _transport 为 None
    proc = MagicMock()
    proc._transport = None
    PrivilegeExecutor._close_transport(proc)  # 不抛即通过


def test_close_transport_swallows_close_exception() -> None:
    """transport.close() 抛异常（已关/平台差异）→ with suppress 兜住不外泄。"""
    proc = MagicMock()
    transport = MagicMock()
    transport.close = MagicMock(side_effect=RuntimeError("Event loop is closed"))
    proc._transport = transport

    # 不抛即通过（suppress(Exception)）
    PrivilegeExecutor._close_transport(proc)
    transport.close.assert_called_once()


def test_timeout_path_closes_transport() -> None:
    """超时 kill 回收后（_kill_and_reap 末尾）显式关 transport。"""
    ex = PrivilegeExecutor()
    ex._timeout = 0.05
    proc = _make_hanging_proc(returncode=-9)
    transport = MagicMock()
    proc._transport = transport

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = asyncio.run(ex.execute(_tool("disk.usage")))

    assert result.exit_code == 124
    transport.close.assert_called_once()  # 超时路径也关 transport


def test_normal_path_closes_transport() -> None:
    """_consume 成功路径（正常完成）也显式关 transport，防长生命周期 FD 累积。"""
    ex = PrivilegeExecutor()
    proc = _make_proc(stdout=b"ok output", stderr=b"", returncode=0)
    transport = MagicMock()
    proc._transport = transport

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = asyncio.run(ex.execute(_tool("disk.usage")))

    assert result.exit_code == 0
    transport.close.assert_called_once()  # 正常完成路径也关 transport


@pytest.mark.skipif(sys.platform == "win32", reason="真子进程超时回收需 POSIX 环境（CI ubuntu 跑）")
def test_real_subprocess_timeout_reaps_process() -> None:
    """真进程：sleep 60 在 1s 超时后被 kill + 回收——proc.returncode 由 None 变为已退出值。

    孤儿泄漏的直接证据：若 except 只 return 不 kill+wait，运行中的 sleep 的 returncode
    保持 None（未回收）；修复后 kill+wait 令内核回收、returncode 被置（-9 SIGKILL）。
    """
    sleep_bin = shutil.which("sleep")
    if sleep_bin is None:
        pytest.skip("无 sleep 命令")

    captured: dict[str, object] = {}
    real_exec = asyncio.create_subprocess_exec

    async def _capture(*args: object, **kwargs: object) -> object:
        proc = await real_exec(*args, **kwargs)  # type: ignore[arg-type]
        captured["proc"] = proc
        return proc

    ex = PrivilegeExecutor()
    ex._timeout = 1
    with patch("asyncio.create_subprocess_exec", _capture):
        result = asyncio.run(ex._run_subprocess(_tool("disk.usage"), [sleep_bin, "60"]))

    assert result.exit_code == 124
    proc = captured["proc"]
    assert proc.returncode is not None, "子进程未被回收——孤儿泄漏（returncode 仍为 None）"


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

    NOTE(D-1d-UPGRADE): PR2 合入并完成接线后，此测试需追加：
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


# ---- systemd 瞬态 service 沙箱包裹（PR2b-v2）------------------------------


def test_sandbox_disabled_by_default() -> None:
    """默认 sandbox_enabled=False：create_subprocess_exec 收原始 argv，不经 wrapper。"""
    from backend.app.executor.sandbox import WRAPPER_PATH

    ex = PrivilegeExecutor()
    mock_proc = _make_proc(stdout=b"ok", returncode=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        asyncio.run(ex.execute(_tool("disk.usage")))

    call_args = mock_exec.call_args
    assert call_args[0][0] == "/usr/bin/df"
    assert WRAPPER_PATH not in call_args[0]


def test_sandbox_enabled_calls_wrapper() -> None:
    """sandbox_enabled=True + Linux：argv 经 wrapper 包裹（非 root 时前置 sudo）。"""
    from backend.app.executor.sandbox import SUDO_PATH, WRAPPER_PATH

    ex = PrivilegeExecutor(sandbox_enabled=True)
    mock_proc = _make_proc(stdout=b"ok", returncode=0)

    with (
        patch("platform.system", return_value="Linux"),
        patch("os.geteuid", return_value=1000, create=True),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec,
    ):
        asyncio.run(ex.execute(_tool("disk.usage")))

    argv = mock_exec.call_args[0]
    assert argv[0] == SUDO_PATH
    assert WRAPPER_PATH in argv
    assert "readonly" in argv  # disk.usage → readonly profile
    # 原命令仍在末尾，未被改写；Python 侧不出现任何 -p 安全属性
    assert argv[-2:] == ("/usr/bin/df", "-PB1")
    assert "-p" not in argv


def test_sandbox_enabled_root_no_sudo() -> None:
    """sandbox_enabled=True + root：直接 wrapper 开头，无 sudo。"""
    from backend.app.executor.sandbox import SUDO_PATH, WRAPPER_PATH

    ex = PrivilegeExecutor(sandbox_enabled=True)
    mock_proc = _make_proc(stdout=b"ok", returncode=0)

    with (
        patch("platform.system", return_value="Linux"),
        patch("os.geteuid", return_value=0, create=True),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec,
    ):
        asyncio.run(ex.execute(_tool("disk.usage")))

    argv = mock_exec.call_args[0]
    assert argv[0] == WRAPPER_PATH
    assert SUDO_PATH not in argv


def test_sandbox_enabled_windows_noop() -> None:
    """Windows 上即使 sandbox_enabled=True 也不包裹。"""
    from backend.app.executor.sandbox import WRAPPER_PATH

    ex = PrivilegeExecutor(sandbox_enabled=True)
    mock_proc = _make_proc(stdout=b"ok", returncode=0)

    with (
        patch("platform.system", return_value="Windows"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec,
    ):
        asyncio.run(ex.execute(_tool("disk.usage")))

    argv = mock_exec.call_args[0]
    assert argv[0] == "/usr/bin/df"
    assert WRAPPER_PATH not in argv


def test_system_info_not_sandboxed() -> None:
    """system.info（profile=none）不走 _run_subprocess，不被沙箱包裹。

    system.info 走 _execute_system_info（仍用 communicate 聚合多命令），故此用例
    保留 communicate mock（与 _run_subprocess 的流式路径不同）。
    """
    from backend.app.executor.sandbox import SUDO_PATH, WRAPPER_PATH

    ex = PrivilegeExecutor(sandbox_enabled=True)
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"x", b""))
    mock_proc.returncode = 0
    # O-H7-1: _execute_system_info finally 里调 _close_transport；给同步 _transport
    # 避免 AsyncMock 自动把 close() 造成协程（RuntimeWarning: never awaited）。
    mock_proc._transport = MagicMock()

    with (
        patch("platform.system", return_value="Linux"),
        patch("os.geteuid", return_value=0, create=True),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec,
    ):
        asyncio.run(ex.execute(_tool("system.info")))

    for call in mock_exec.call_args_list:
        assert call[0][0] not in (WRAPPER_PATH, SUDO_PATH)
