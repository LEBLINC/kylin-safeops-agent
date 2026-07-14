"""deploy/sso/tests conftest: 钉 KYLIN_PROXY_AUTH_SECRET env (proxy.py 模块级读)."""

import pytest


@pytest.fixture(autouse=True)
def _proxy_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", "test-secret-for-deploy-sso-tests")
