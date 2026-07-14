"""A2.2: start.bat 模板必含关键 env 守门（1 用例 T8）.

决策⑨硬阻断：反代生产部署禁止 KYLIN_LDAP_MOCK=true。本用例锁死 start.bat
必须显式设置 KYLIN_PROXY_AUTH_SECRET + KYLIN_LDAP_MOCK=false，防止部署脚本
漂移成误留 mock 模式（ADR-0004 fail-closed 的前置条件）。
"""

from __future__ import annotations

import pathlib


def test_t8_start_bat_sets_required_env() -> None:
    """T8: start.bat 必含 KYLIN_PROXY_AUTH_SECRET 设置 + KYLIN_LDAP_MOCK=false."""
    path = pathlib.Path(__file__).resolve().parents[1] / "start.bat"
    assert path.exists(), f"T8: start.bat 不存在于 {path}"
    text = path.read_text(encoding="utf-8")
    assert "KYLIN_PROXY_AUTH_SECRET" in text, "T8: start.bat 必设 KYLIN_PROXY_AUTH_SECRET"
    assert (
        "KYLIN_LDAP_MOCK=false" in text
    ), "T8: start.bat 必须 KYLIN_LDAP_MOCK=false（决策⑨禁止生产反代用 mock）"
