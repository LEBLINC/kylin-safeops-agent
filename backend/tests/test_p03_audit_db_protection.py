"""P0-3: 审计库不得被合法 R2 操作抹掉（策略闸 + 沙箱 wrapper 两道独立闸）。

修前两道闸同时漏：
  ① 策略层：/var/lib/kylin-safeops 不在 forbid_modify/forbid_delete 任一清单，
     log.compress_rotate{path:"/var/lib/kylin-safeops/audit.db"} 仅判
     confirm/operator → operator 点一次批准即以 root gzip 掉审计库。
  ② wrapper 层：只有 find/systemctl 两个 case，gzip 无任何限制 → 即便策略闸
     被绕过或日后放宽，沙箱层也拦不住。

危害不止"丢数据"：整条哈希链连同证据一起消失，app 下次写入自动新建空库，
而**空链的 verify_chain 返 valid** —— 事后完全看不出发生过什么。
审计是本系统的最终证据面，不能由被审计者销毁。

策略层（拦在批准之前）：
  A-1 gzip 审计库 → deny（不再是 confirm/operator）
  A-2 gzip 自身代码/venv → deny
  A-3 正常轮转 /var/log 仍 confirm（零误伤）
  A-4 forbid_modify 清单确含两条新路径
wrapper 层（沙箱兜底，与策略层独立）：
  W-1 gzip 审计库 / 自身代码 / /etc → 拒
  W-2 gzip 路径穿越（/var/log/../lib/...）→ 拒
  W-3 gzip 选项注入 / 多参数 / 零参数 → 拒
  W-4 journalctl --vacuum-*/--rotate/--flush → 拒
  W-5 合法模板 argv 全部放行（零误伤）
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

from backend.app.api._fakes import build_gateway
from backend.app.contracts.intent import CandidateTool

_AUDIT_DB = "/var/lib/kylin-safeops/audit.db"
_OWN_CODE = "/opt/kylin-safeops/backend/app/api/auth.py"
_WRAPPER = (
    pathlib.Path(__file__).resolve().parents[2] / "deploy" / "sandbox" / "kylin-safeops-run.sh"
)


def _verdict(path: str):
    return build_gateway().evaluate(CandidateTool(name="log.compress_rotate", args={"path": path}))


# ---- 策略层 ---------------------------------------------------------------


def test_a1_policy_denies_gzip_audit_db() -> None:
    """A-1: 压缩审计库必须 deny——confirm 意味着"有人点批准就能销毁证据"。"""
    v = _verdict(_AUDIT_DB)
    assert (
        v.decision == "deny"
    ), f"A-1: 审计库仍可被批准销毁（decision={v.decision}, role={v.approval_role}）"
    assert "PATH_FORBID_MODIFY" in v.matched_rules


def test_a2_policy_denies_gzip_own_code() -> None:
    """A-2: 压缩自身代码/venv 必须 deny（否则可让服务下次启动即失败）。"""
    assert _verdict(_OWN_CODE).decision == "deny"


def test_a3_normal_log_rotation_still_confirm() -> None:
    """A-3: 零误伤——/var/log 下正常轮转仍走 confirm 审批，不得被堵死。"""
    v = _verdict("/var/log/app.log")
    assert v.decision == "confirm", f"A-3: 正常轮转被误堵（{v.decision}）"
    assert "PATH_ROTATE_ONLY" in v.matched_rules


def test_a4_forbid_modify_covers_runtime_paths() -> None:
    """A-4: 清单本身含两条路径（防日后被"整理"掉而无人察觉）。"""
    from backend.app.security.policy_loader import DEFAULT_POLICY_DICT

    forbid = DEFAULT_POLICY_DICT["protected_paths"]["forbid_modify"]
    assert "/var/lib/kylin-safeops" in forbid, "A-4: 审计库目录不在 forbid_modify"
    assert "/opt/kylin-safeops" in forbid, "A-4: 安装目录不在 forbid_modify"


# ---- wrapper 层（与策略层独立的第二道闸）---------------------------------

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="wrapper 校验需 bash 解释")


@pytest.fixture(scope="module")
def stub_wrapper(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """把 SYSTEMD_RUN 换成 /bin/echo——参数校验在 exec 之前，故无需真 systemd。"""
    src = _WRAPPER.read_text(encoding="utf-8")
    assert "SYSTEMD_RUN=/usr/bin/systemd-run" in src, "wrapper 结构变化，stub 失效"
    dest = tmp_path_factory.mktemp("p03") / "wrapper.sh"
    dest.write_text(
        src.replace("SYSTEMD_RUN=/usr/bin/systemd-run", "SYSTEMD_RUN=/bin/echo"),
        encoding="utf-8",
    )
    return dest


def _run(wrapper: pathlib.Path, profile: str, inner: list[str]):
    return subprocess.run(
        ["bash", str(wrapper), profile, "--", *inner],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )


@pytest.mark.parametrize("target", [_AUDIT_DB, _OWN_CODE, "/etc/passwd"])
def test_w1_wrapper_rejects_gzip_outside_var_log(stub_wrapper: pathlib.Path, target: str) -> None:
    """W-1: wrapper 层只放行 /var/log 下的 gzip（策略闸之外的第二道闸）。"""
    r = _run(stub_wrapper, "limited_write", ["/usr/bin/gzip", target])
    assert r.returncode != 0, f"W-1: wrapper 放行了 gzip {target}"
    assert "参数被拒" in r.stderr


def test_w2_wrapper_rejects_path_traversal(stub_wrapper: pathlib.Path) -> None:
    """W-2: 前缀匹配挡不住 /var/log/../lib/... ——必须单独拒 .. 穿越。"""
    r = _run(
        stub_wrapper,
        "limited_write",
        ["/usr/bin/gzip", "/var/log/../lib/kylin-safeops/audit.db"],
    )
    assert r.returncode != 0, "W-2: 路径穿越绕过了 /var/log 前缀检查"
    assert ".." in r.stderr


@pytest.mark.parametrize(
    "inner",
    [
        ["/usr/bin/gzip", "-f", "/var/log/app.log"],
        ["/usr/bin/gzip", "-r", "/var/log"],
        ["/usr/bin/gzip", "/var/log/a.log", "/var/log/b.log"],
        ["/usr/bin/gzip"],
    ],
)
def test_w3_wrapper_rejects_gzip_options_and_multiarg(
    stub_wrapper: pathlib.Path, inner: list[str]
) -> None:
    """W-3: gzip 只接受恰好 1 个文件参数，拒一切选项与批量。"""
    r = _run(stub_wrapper, "limited_write", inner)
    assert r.returncode != 0, f"W-3: wrapper 放行了 {inner}"


@pytest.mark.parametrize(
    "flag",
    ["--vacuum-time=1s", "--vacuum-size=1K", "--vacuum-files=1", "--rotate", "--flush"],
)
def test_w4_wrapper_rejects_journalctl_destructive(stub_wrapper: pathlib.Path, flag: str) -> None:
    """W-4: journalctl 的日志销毁/轮转开关必须拒——否则可 root 清空 journal。"""
    r = _run(stub_wrapper, "readonly", ["/usr/bin/journalctl", flag])
    assert r.returncode != 0, f"W-4: wrapper 放行了 journalctl {flag}"
    assert "参数被拒" in r.stderr


@pytest.mark.parametrize(
    "inner",
    [
        ["/usr/bin/gzip", "/var/log/app.log"],
        ["/usr/bin/journalctl", "--no-pager", "-u", "cron", "-n", "50"],
        ["/usr/bin/journalctl", "--no-pager", "-p", "3", "-S", "today"],
    ],
)
def test_w5_wrapper_allows_legit_template_argv(
    stub_wrapper: pathlib.Path, inner: list[str]
) -> None:
    """W-5: 零误伤——命令模板实际生成的 argv 必须全部放行。"""
    r = _run(stub_wrapper, "limited_write", inner)
    assert r.returncode == 0, f"W-5: 误伤合法调用 {inner}: {r.stderr!r}"
