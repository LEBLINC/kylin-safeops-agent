"""B2: proxy.py mock fail-fast 守卫（ADR-0004 第四道保险）守门测试.

_fail_fast_if_mock_in_production() 在模块 import 期执行（顶层调用，非函数内），
无法用 pytest monkeypatch 覆盖已加载的模块——必须用子进程真实起一次 import
才能验证 SystemExit(1) 行为（否则测试只是"调了函数"而非"进程真的被拒启动"）。

覆盖 2 用例：
  T1 KYLIN_LDAP_MOCK=true（无 opt-out）→ 子进程 import 即 exit code 1
  T2 KYLIN_LDAP_MOCK=false → 子进程 import 正常（exit code 0，不到达 uvicorn.run）
"""

from __future__ import annotations

import os
import subprocess
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _run_import_in_subprocess(env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    """子进程跑 `import deploy.proxy.proxy`（不起 uvicorn，只测模块级 fail-fast）。"""
    env = os.environ.copy()
    # KYLIN_PROXY_AUTH_SECRET 未设不影响本测试（fail-fast 检查在 LdapClient() 之前）,
    # 但 LdapClient() 构造本身不抛（P1b 设计：真模式缺配置不 raise，只是 _real_cfg 空）。
    env.update(env_overrides)
    code = "import deploy.proxy.proxy"
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_t1_mock_true_without_optout_exits_1() -> None:
    """T1: KYLIN_LDAP_MOCK=true 且无 KYLIN_PROXY_ALLOW_MOCK → 子进程 exit code 1."""
    result = _run_import_in_subprocess({"KYLIN_LDAP_MOCK": "true", "KYLIN_PROXY_ALLOW_MOCK": ""})
    assert result.returncode == 1, (
        f"T1: mock=true 无 opt-out 应 fail-fast exit 1, "
        f"got {result.returncode}, stderr={result.stderr!r}"
    )
    assert "ADR-0004" in result.stderr, f"T1: stderr 应含 ADR-0004 提示, got {result.stderr!r}"


def test_t2_mock_false_imports_normally() -> None:
    """T2: KYLIN_LDAP_MOCK=false → 子进程 import 正常退出 (exit code 0)."""
    result = _run_import_in_subprocess({"KYLIN_LDAP_MOCK": "false"})
    assert (
        result.returncode == 0
    ), f"T2: mock=false 应正常 import, got {result.returncode}, stderr={result.stderr!r}"


def test_t3_mock_true_with_optout_imports_normally() -> None:
    """T3: KYLIN_LDAP_MOCK=true + KYLIN_PROXY_ALLOW_MOCK=true → 显式 opt-out 放行."""
    result = _run_import_in_subprocess(
        {"KYLIN_LDAP_MOCK": "true", "KYLIN_PROXY_ALLOW_MOCK": "true"}
    )
    assert (
        result.returncode == 0
    ), f"T3: 显式 opt-out 应放行, got {result.returncode}, stderr={result.stderr!r}"
