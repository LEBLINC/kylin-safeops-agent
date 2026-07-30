r"""之七十五 H-1: wrapper 逐参数校验守门。

首 argv 白名单只保证"跑哪个二进制"，不保证"用它做什么"——白名单里的
find 与 systemctl 各自自带把只读命令升级为任意执行/拒绝服务的开关：
    find <path> -exec rm -rf {} \;   → 任意命令执行（且以 root）
    systemctl mask sshd               → 拒绝服务
两者都不需要换二进制即可越过白名单语义，H-1 因此按命令逐参数校验。

本用例**不依赖 systemd**：参数校验发生在 wrapper 调 systemd-run 之前，
故 reject 路径只需 bash 即可验证（Windows/Linux 均可跑，不进 skip 名单）。
accept 路径把 SYSTEMD_RUN 替换为 /bin/echo，只验"校验放行"，不验沙箱本身
（真沙箱由 test_sandbox.py 的集成层在 Linux + systemd 上覆盖）。

  H1-1 现有 15 工具的真实 argv 全部放行（零误伤）
  H1-2 find 动作类谓词全部被拒（-exec/-execdir/-delete/-ok/-fprintf...）
  H1-3 find 未列入白名单的选项被拒（挡未来新增危险谓词）
  H1-4 systemctl 动词白名单外全部被拒（mask/stop/kill/isolate/缺动词）
  H1-5 systemctl 动词后的选项注入被拒（--signal=KILL 类）
  H1-6 KYLIN_SANDBOX_TEST=1 注入分支不被新校验波及（touch/echo/true/false）
  H1-7 未设 KYLIN_SANDBOX_TEST 时测试二进制仍被首 argv 白名单拒（生产面不变）
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER = _REPO_ROOT / "deploy" / "sandbox" / "kylin-safeops-run.sh"

_needs_bash = pytest.mark.skipif(
    shutil.which("bash") is None, reason="wrapper 校验逻辑需 bash 解释（Linux CI / Git Bash 均可）"
)


@pytest.fixture(scope="module")
def stub_wrapper(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """把 SYSTEMD_RUN 替换为 /bin/echo 的 wrapper 副本。

    参数校验在 exec systemd-run 之前完成，替换后即可在无 systemd 的机器上
    区分"校验放行"(exit 0) 与"校验拒绝"(exit 1)。安全属性不参与本用例判定。
    """
    src = _WRAPPER.read_text(encoding="utf-8")
    assert "SYSTEMD_RUN=/usr/bin/systemd-run" in src, "wrapper 结构变化，stub 失效"
    stubbed = src.replace("SYSTEMD_RUN=/usr/bin/systemd-run", "SYSTEMD_RUN=/bin/echo")
    dest = tmp_path_factory.mktemp("h1") / "wrapper.sh"
    dest.write_text(stubbed, encoding="utf-8")
    return dest


#: wrapper 的参数校验拒绝码（与"命令不在白名单"的 1 区分，见 wrapper reject()）。
_EXIT_ARG_REJECTED = 2
#: 命令白名单拒绝码。
_EXIT_CMD_REJECTED = 1


def _run(wrapper: Path, profile: str, inner: list[str], *, test_mode: bool = False):
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    if test_mode:
        env["KYLIN_SANDBOX_TEST"] = "1"
    return subprocess.run(
        ["bash", str(wrapper), profile, "--", *inner],
        capture_output=True,
        text=True,
        # 必须显式指定：wrapper 的拒绝理由是中文，GBK locale 下 text=True
        # 用系统编码解码会失败，stderr 变 None，20 条断言全部 TypeError。
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=env,
    )


# ---- H1-1 零误伤：现有 15 工具的真实 argv ---------------------------------

# 逐条对齐 command_templates.py 的 argv_prefix/dynamic_args/flag_map
# 与 privilege_executor._tool_specific_argv 的补全结果。
_LEGIT_INVOCATIONS = [
    ("readonly", ["/usr/bin/df", "-PB1"]),
    ("readonly", ["/usr/bin/find", "/var", "-type", "f", "-printf", "%s\t%p\n"]),
    (
        "readonly",
        ["/usr/bin/find", "/var/log", "-type", "f", "-name", "*.log", "-printf", "%s\t%p\n"],
    ),
    ("readonly", ["/usr/bin/ps", "aux"]),
    ("readonly", ["/usr/sbin/ss", "-tulnp"]),
    ("readonly", ["/usr/bin/netstat", "-tulnp"]),
    ("readonly", ["/usr/bin/journalctl", "--no-pager", "-u", "cron", "-n", "50"]),
    ("readonly", ["/usr/bin/lsof", "-p", "123"]),
    ("readonly", ["/usr/bin/lsof", "/var/log/app.log", "--"]),
    ("readonly", ["/usr/bin/systemctl", "show", "nginx.service"]),
    ("readonly", ["/usr/bin/sha256sum", "/etc/hosts"]),
    ("readonly", ["/usr/bin/vmstat", "1", "2"]),
    ("readonly", ["/usr/bin/free", "-b"]),
    ("limited_write", ["/usr/bin/systemctl", "restart", "nginx.service"]),
    ("limited_write", ["/usr/bin/gzip", "/var/log/app.log"]),
]


@_needs_bash
@pytest.mark.parametrize(("profile", "inner"), _LEGIT_INVOCATIONS)
def test_h1_1_legit_tool_argv_all_accepted(
    stub_wrapper: Path, profile: str, inner: list[str]
) -> None:
    """H1-1: 15 个生产工具的真实 argv 一个都不能被新校验误伤。"""
    result = _run(stub_wrapper, profile, inner)
    assert result.returncode == 0, f"误伤 {inner}：rc={result.returncode} stderr={result.stderr!r}"
    assert "参数被拒" not in result.stderr


# ---- H1-2 / H1-3 find ------------------------------------------------------

_FIND_ACTION_PREDICATES = [
    ["/usr/bin/find", "/", "-exec", "rm", "-rf", "{}", ";"],
    ["/usr/bin/find", "/tmp", "-delete"],
    ["/usr/bin/find", "/", "-execdir", "sh", "-c", "id", ";"],
    ["/usr/bin/find", "/", "-ok", "rm", "{}", ";"],
    ["/usr/bin/find", "/", "-okdir", "rm", "{}", ";"],
    ["/usr/bin/find", "/", "-fprintf", "/etc/passwd", "%p"],
    ["/usr/bin/find", "/", "-fprint", "/etc/passwd"],
    ["/usr/bin/find", "/", "-fls", "/etc/passwd"],
]


@_needs_bash
@pytest.mark.parametrize("inner", _FIND_ACTION_PREDICATES)
def test_h1_2_find_action_predicates_rejected(stub_wrapper: Path, inner: list[str]) -> None:
    """H1-2: find 的动作类谓词（可执行命令 / 删除 / 写文件）一律拒。"""
    result = _run(stub_wrapper, "readonly", inner)
    assert (
        result.returncode == _EXIT_ARG_REJECTED
    ), f"{inner} 应被参数校验拒（exit {_EXIT_ARG_REJECTED}），实际 rc={result.returncode}"
    # 断到该谓词自身，不共用 "参数被拒" 前缀——共用前缀时任一分支改动
    # 会让多条断言同时失效或同时假绿。
    predicate = inner[2]
    assert predicate in result.stderr, f"拒绝理由未点名 {predicate}：{result.stderr!r}"


@_needs_bash
def test_h1_3_find_unknown_option_rejected(stub_wrapper: Path) -> None:
    """H1-3: find 只允许 -type/-printf/-name；其它选项一律拒（挡未来新增谓词）。"""
    result = _run(stub_wrapper, "readonly", ["/usr/bin/find", "/", "-newer", "/etc/shadow"])
    assert result.returncode == _EXIT_ARG_REJECTED
    assert "-newer" in result.stderr, f"拒绝理由未点名 -newer：{result.stderr!r}"
    assert "仅允许 -type/-printf/-name" in result.stderr


# ---- H1-4 / H1-5 systemctl -------------------------------------------------


@_needs_bash
@pytest.mark.parametrize("verb", ["mask", "stop", "kill", "isolate", "disable", "poweroff"])
def test_h1_4_systemctl_verb_whitelist(stub_wrapper: Path, verb: str) -> None:
    """H1-4: systemctl 动词仅 show/restart；mask/stop/kill/isolate 等一律拒。"""
    result = _run(stub_wrapper, "limited_write", ["/usr/bin/systemctl", verb, "sshd"])
    assert (
        result.returncode == _EXIT_ARG_REJECTED
    ), f"systemctl {verb} 应被拒，实际 rc={result.returncode}"
    assert verb in result.stderr, f"拒绝理由未点名动词 {verb}：{result.stderr!r}"
    assert "动词仅允许 show/restart" in result.stderr


@_needs_bash
def test_h1_4b_systemctl_missing_verb_rejected(stub_wrapper: Path) -> None:
    """H1-4b: 缺动词 → 拒（不给 systemctl 裸跑的机会）。"""
    result = _run(stub_wrapper, "readonly", ["/usr/bin/systemctl"])
    assert result.returncode == _EXIT_ARG_REJECTED
    assert "缺少动词" in result.stderr


@_needs_bash
@pytest.mark.parametrize(
    ("inner", "expect_in_reason"),
    [
        # 动词合法（restart/show），故真正触发的是"动词之后的选项注入"分支
        (["/usr/bin/systemctl", "restart", "--force", "sshd"], "--force"),
        (["/usr/bin/systemctl", "show", "--property=ExecStart", "-p", "x"], "--property=ExecStart"),
        # 动词本身就不合法 → 在动词闸即被拒，压根到不了选项检查。
        # 断言点名 kill 而非 --signal=KILL：写后者会把"拒在哪一道闸"记错，
        # 日后动词白名单放开 kill 时这条会静默失去意义。
        (["/usr/bin/systemctl", "kill", "--signal=KILL", "sshd"], "kill"),
    ],
)
def test_h1_5_systemctl_option_injection_rejected(
    stub_wrapper: Path, inner: list[str], expect_in_reason: str
) -> None:
    """H1-5: 动词之后只接受服务名/属性名，选项注入一律拒。"""
    result = _run(stub_wrapper, "limited_write", inner)
    assert result.returncode == _EXIT_ARG_REJECTED, f"{inner} 应被拒，实际 rc={result.returncode}"
    assert (
        expect_in_reason in result.stderr
    ), f"拒绝理由未点名 {expect_in_reason}：{result.stderr!r}"


# ---- H1-6 / H1-7 测试注入分支不受波及 --------------------------------------


@_needs_bash
@pytest.mark.parametrize(
    ("profile", "inner"),
    [
        ("limited_write", ["/usr/bin/touch", "/tmp/h1probe"]),
        ("readonly", ["/usr/bin/echo", "hello"]),
        ("readonly", ["/usr/bin/echo", "-n", "hi"]),
        ("readonly", ["/bin/true"]),
        ("readonly", ["/bin/false"]),
    ],
)
def test_h1_6_sandbox_test_injection_unaffected(
    stub_wrapper: Path, profile: str, inner: list[str]
) -> None:
    """H1-6: KYLIN_SANDBOX_TEST=1 的 touch/echo/true/false 不被新校验拦。

    新增的逐参数校验只对 find / systemctl 生效（case 分支），测试二进制不受影响。
    """
    result = _run(stub_wrapper, profile, inner, test_mode=True)
    assert result.returncode == 0, f"测试注入分支被误伤 {inner}: stderr={result.stderr!r}"
    assert "参数被拒" not in result.stderr


@_needs_bash
def test_h1_7_production_still_rejects_test_binaries(stub_wrapper: Path) -> None:
    """H1-7: 未设 KYLIN_SANDBOX_TEST → 测试二进制仍被首 argv 白名单拒（生产面不变）。"""
    result = _run(stub_wrapper, "limited_write", ["/usr/bin/touch", "/tmp/x"], test_mode=False)
    assert (
        result.returncode == _EXIT_CMD_REJECTED
    ), f"命令白名单拒绝应为 exit {_EXIT_CMD_REJECTED}，实际 {result.returncode}"
    assert result.returncode != _EXIT_ARG_REJECTED, "H1-7: 命令白名单拒绝不得与参数校验拒绝同码"
    assert "命令不在白名单" in result.stderr
