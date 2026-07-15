"""B1b: nginx.conf 加固守门（架构审计 154f767 §2 B1）.

审计发现：nginx 直连 127.0.0.1:8000（app），完全绕过 proxy sidecar，无 TLS、
不剥客户端伪造的 X-Auth-* 头、无安全响应头、无限流——前门形同虚设。
本用例锁死加固后的 nginx.conf 必须同时满足：
  T12 监听 443 ssl（TLS，非纯 80 明文业务）
  T13 upstream 是 sidecar 8080（不是 app 的 8000，防绕过反代）
  T14 显式剥离全部 8 个 X-Auth-* / X-User-Role 客户端伪造头
  T15 三项安全响应头齐全（HSTS/X-Frame-Options/X-Content-Type-Options）
  T16 limit_req 限流已接线（zone 引用存在）
"""

from __future__ import annotations

import pathlib


def _nginx_text() -> str:
    path = pathlib.Path(__file__).resolve().parents[2] / "nginx.conf"
    assert path.exists(), f"nginx.conf 不存在于 {path}"
    return path.read_text(encoding="utf-8")


def test_t12_listens_on_443_ssl() -> None:
    """T12: 必须监听 443 ssl（TLS 业务端口；80 仅允许跳转）."""
    text = _nginx_text()
    assert "listen 443 ssl" in text, "T12: 必须 listen 443 ssl（TLS）"
    assert "return 301 https" in text, "T12: 80 端口应重定向到 https，不直接服务业务"


def test_t13_upstream_is_sidecar_8080_not_app_8000() -> None:
    """T13: proxy_pass 必须指向 sidecar 8080，不得直连 app 的 8000（防绕过反代鉴权）."""
    text = _nginx_text()
    assert "proxy_pass http://127.0.0.1:8080" in text, "T13: 必须反代到 sidecar 8080"
    assert (
        "proxy_pass http://127.0.0.1:8000" not in text
    ), "T13: 不得直连 app 8000（绕过 sidecar 鉴权/签名注入）"


def test_t14_strips_all_client_forged_auth_headers() -> None:
    """T14: 必须显式清空全部 8 个客户端可能伪造的签名/角色头."""
    text = _nginx_text()
    required = [
        "X-Auth-User",
        "X-Auth-Roles",
        "X-Auth-Timestamp",
        "X-Auth-Signature",
        "X-Auth-Method",
        "X-Auth-Path",
        "X-Auth-Body-Sha",
        "X-Auth-Nonce",
        "X-User-Role",
    ]
    for header in required:
        assert (
            f'proxy_set_header {header} ""' in text
        ), f"T14: 必须剥离客户端伪造头 {header}（防绕过签名鉴权）"


def test_t15_security_headers_present() -> None:
    """T15: HSTS / X-Frame-Options / X-Content-Type-Options 三项安全头齐全."""
    text = _nginx_text()
    assert "Strict-Transport-Security" in text, "T15: 缺 HSTS"
    assert "X-Frame-Options" in text, "T15: 缺 X-Frame-Options"
    assert "X-Content-Type-Options" in text, "T15: 缺 X-Content-Type-Options"


def test_t16_rate_limiting_wired() -> None:
    """T16: limit_req 限流已在 /api/ location 接线（zone 引用存在）."""
    text = _nginx_text()
    assert "limit_req zone=" in text, "T16: /api/ location 必须接 limit_req 限流"
    assert "limit_req_zone" in text, "T16: 需在注释/说明中给出 limit_req_zone 声明（http{} 作用域）"
