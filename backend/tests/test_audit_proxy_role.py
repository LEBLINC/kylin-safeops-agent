"""L-B2 偏差 4: proxy 模式严测（fixture 用法示例 + 守门回归保护）。

覆盖 2 用例：
  T1: audit list_traces proxy mode admin → 200
  T2: audit list_traces proxy mode viewer → 403（不在 {auditor, admin}）
"""

from __future__ import annotations


def test_t1_audit_proxy_mode_admin_allowed(
    monkeypatch, proxy_mode_client, proxy_signed_headers
) -> None:
    """T1: proxy 模式 + HMAC-signed admin → 200（签过 + role ∈ admin）。"""
    headers = proxy_signed_headers("alice_admin", roles="admin")
    resp = proxy_mode_client("/api/audit/traces", headers=headers)
    assert resp.status_code == 200, resp.text


def test_t2_audit_proxy_mode_viewer_denied(
    monkeypatch, proxy_mode_client, proxy_signed_headers
) -> None:
    """T2: proxy 模式 + HMAC-signed viewer → 403（不在 auditor/admin 角色集）。"""
    headers = proxy_signed_headers("bob_viewer", roles="viewer")
    resp = proxy_mode_client("/api/audit/traces", headers=headers)
    assert resp.status_code == 403, resp.text
