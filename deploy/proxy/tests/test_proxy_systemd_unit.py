"""B1a: kylin-proxy.service systemd unit 模板守门（架构审计 154f767 §2 B1）.

审计发现：deploy/ 只有 app 单元（kylin-safeops.service），proxy sidecar
无 systemd unit——生产部署根本没有独立可信代理进程，nginx 只能直连 app（B1）。
本用例锁死 kylin-proxy.service 必须存在且满足最低安全要求：
  T9  必含 EnvironmentFile（密钥/LDAP 配置不硬编码进 unit）
  T10 User 非 root（最小权限）
  T11 ExecStart 监听端口 8080（与 nginx upstream / start.bat 口径一致）
"""

from __future__ import annotations

import pathlib
import re


def _unit_text() -> str:
    path = pathlib.Path(__file__).resolve().parents[1] / "kylin-proxy.service"
    assert path.exists(), f"kylin-proxy.service 不存在于 {path}"
    return path.read_text(encoding="utf-8")


def test_t9_unit_uses_environment_file_not_hardcoded_secret() -> None:
    """T9: unit 必含 EnvironmentFile（密钥/LDAP 配置带外注入，不硬编码进 unit 文件）."""
    text = _unit_text()
    assert "EnvironmentFile=" in text, "T9: kylin-proxy.service 必须用 EnvironmentFile 带外注入配置"
    # 不得硬编码真实密钥值（占位符/路径引用允许）
    assert (
        "KYLIN_PROXY_AUTH_SECRET=" not in text
    ), "T9: KYLIN_PROXY_AUTH_SECRET 不得硬编码进 unit 文件，必须走 EnvironmentFile"


def test_t10_unit_runs_as_non_root_user() -> None:
    """T10: unit 必须 User=非 root（最小权限，proxy 不需要 root）."""
    text = _unit_text()
    m = re.search(r"^User=(\S+)", text, re.MULTILINE)
    assert m is not None, "T10: kylin-proxy.service 必须显式设置 User="
    assert m.group(1) != "root", f"T10: proxy 单元不得以 root 运行, got User={m.group(1)}"


def test_t11_unit_listens_on_port_8080() -> None:
    """T11: ExecStart 必须监听 8080（与 nginx upstream / start.bat 口径一致，非直连 app 8000）."""
    text = _unit_text()
    assert "--port 8080" in text, "T11: proxy sidecar 必须监听 8080（不是 app 的 8000）"
    assert "deploy.proxy.proxy:app" in text, "T11: ExecStart 必须启动 deploy.proxy.proxy:app"
