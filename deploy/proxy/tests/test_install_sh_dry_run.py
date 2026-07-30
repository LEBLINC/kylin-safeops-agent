"""B1c: install.sh 双单元 + proxy.env 骨架 守门（架构审计 154f767 §2 B1）.

审计发现：install.sh 只装 kylin-safeops.service（app 单元），从未装 proxy sidecar
单元——即便 B1a 造好了 kylin-proxy.service，标准部署脚本也不会安装它，运维手动
补装才行，等同于"钥匙已配好但从不发"。本用例用真实 `bash install.sh --dry-run`
（不需 root，脚本 dry-run 分支只打印不执行）验证修复后的脚本确实覆盖：
  T17 dry-run 输出提及双单元（app + kylin-proxy）
  T18 dry-run 输出提及非 root 用户创建（kylin-safeops，幂等 id 检查）
  T19 dry-run 输出提及 /etc/kylin/proxy.env 骨架创建
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

_INSTALL_SH = pathlib.Path(__file__).resolve().parents[3] / "deploy" / "install.sh"

# skip 谓词按"bash 是否可用"判定，而非按平台：Windows 上装了 Git Bash 时
# shutil.which("bash") 有值，用例能真跑；按 sys.platform=="win32" 判会把这些
# 环境一并 skip，与 test_wrapper_arg_validation.py 的谓词也不一致
# （同一前提两套判据 → 两个文件在同一台机器上一个跑一个不跑）。
_REQUIRES_BASH = pytest.mark.skipif(
    shutil.which("bash") is None,
    reason="install.sh dry-run needs bash（Linux CI / Git Bash 均可）",
)


def _dry_run_output() -> str:
    result = subprocess.run(
        ["bash", str(_INSTALL_SH), "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert (
        result.returncode == 0
    ), f"install.sh --dry-run 应 exit 0, got {result.returncode}: {result.stderr}"
    return result.stdout


@_REQUIRES_BASH
def test_t17_dry_run_installs_both_units() -> None:
    """T17: dry-run 输出必含双单元安装（app + kylin-proxy sidecar）。"""
    out = _dry_run_output()
    assert "kylin-safeops-agent.service" in out, "T17: 必装 app 单元（之七十五 R-3 收敛后的完整版）"
    assert "kylin-proxy.service" in out, "T17: 必装 proxy sidecar 单元（B1 前门洞修复）"


@_REQUIRES_BASH
def test_t18_dry_run_creates_nonroot_user_idempotent() -> None:
    """T18: dry-run 输出必含非 root 系统用户创建（幂等 id 检查）。"""
    out = _dry_run_output()
    assert "kylin-safeops" in out
    assert "useradd" in out or "id -u kylin-safeops" in out, "T18: 必含幂等用户创建逻辑"


@_REQUIRES_BASH
def test_t19_dry_run_scaffolds_proxy_env() -> None:
    """T19: dry-run 输出必含 /etc/kylin/proxy.env 骨架创建提示。"""
    out = _dry_run_output()
    assert "/etc/kylin/proxy.env" in out, "T19: 必创建 proxy sidecar 密钥/LDAP 配置骨架"
