"""B5 commit 1 L-H12: deploy/{sso,proxy} smoke import test。

deploy/ 不在 pytest testpaths 的 root conftest 作用域,根级 backend/tests
放 import smoke 测试更稳 (避免 'tests' namespace 冲突)。
"""

from __future__ import annotations

import pytest


def test_deploy_sso_imports_smoke() -> None:
    """T1: deploy/sso 模块导入不 raise (mypy files regex 已覆盖)。"""
    import deploy.sso.ldap_client  # noqa: F401


def test_deploy_proxy_imports_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """T2: deploy/proxy 模块导入不 raise (需先设 KYLIN_PROXY_AUTH_SECRET env)。"""
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", "test-secret-for-smoke")
    import deploy.proxy.proxy  # noqa: F401
