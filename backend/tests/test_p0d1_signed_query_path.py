"""P0-D1: 带 query 的签名请求被等值断言全部打成 401。

P1-5 的等值断言引入了字节级口径不一致：

  签名方 deploy/proxy/proxy.py:123-125
      full_path = f"/{path}"
      if request.url.query: full_path = f"{full_path}?{query}"   ← 含 query
      → 写进 X-Auth-Path

  校验方 backend/app/api/deps.py
      actual_path = request.url.path                              ← 不含 query

⇒ 任何带 query 的请求：x_auth_path != actual_path → 401 path mismatch。
HMAC 本身是过的（报文是 "path mismatch" 而非 "invalid proxy-signed identity"），
是新加的断言把它杀掉的。proxy 是生产默认模式，故这条让整个 B/S 前门半瘫：
审批页 status=pending、工具历史 tool/limit、策略命中 trace_id、系统趋势 hours、
会话搜索 keyword —— 全部 401。

988 条既有用例零覆盖：test_deps_v2_proxy_verify.py 从来不发 query。

  Q-1 带单个 query 参数的签名请求必须通过（回归锚点）
  Q-2 带多个 query 参数同样通过
  Q-3 多值同名键（?a=1&a=2）通过——转发若用 dict() 会塌陷，此处钉住原样透传
  Q-4 无 query 的请求不回归
  Q-5 篡改 query 后必须仍然 401——防"干脆不比 path"式的假修复
  Q-6 篡改 path 后必须仍然 401（等值断言主职责不丢）
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid

import httpx
import pytest

_SECRET = "d1-test-secret-do-not-use-in-prod"


def _signed_headers(method: str, full_path: str, body: bytes = b"") -> dict[str, str]:
    """按 proxy.py 的真实口径造签名头：X-Auth-Path 含 query。"""
    from deploy.proxy._sign import sign

    user = "alice"
    roles = "operator"
    ts = str(int(time.time()))
    body_sha = hashlib.sha256(body).hexdigest()
    nonce = uuid.uuid4().hex
    return {
        "X-Auth-User": user,
        "X-Auth-Roles": roles,
        "X-Auth-Timestamp": ts,
        "X-Auth-Signature": sign(user, roles, ts, method, full_path, body_sha, nonce),
        "X-Auth-Method": method,
        "X-Auth-Path": full_path,
        "X-Auth-Body-Sha": body_sha,
        "X-Auth-Nonce": nonce,
    }


def _get(url_path: str, *, sign_path: str | None = None) -> httpx.Response:
    """以 proxy 模式打真 app；sign_path 默认与 url_path 一致（正常场景）。"""
    from backend.app.api.app import create_app, lifespan

    signed = sign_path if sign_path is not None else url_path

    async def _scenario() -> httpx.Response:
        app = create_app()
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(url_path, headers=_signed_headers("GET", signed))

    old_mode = os.environ.get("KYLIN_AUTH_MODE")
    old_secret = os.environ.get("KYLIN_PROXY_AUTH_SECRET")
    os.environ["KYLIN_AUTH_MODE"] = "proxy"
    os.environ["KYLIN_PROXY_AUTH_SECRET"] = _SECRET
    try:
        return asyncio.run(_scenario())
    finally:
        for key, val in (
            ("KYLIN_AUTH_MODE", old_mode),
            ("KYLIN_PROXY_AUTH_SECRET", old_secret),
        ):
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def _assert_not_path_mismatch(resp: httpx.Response, label: str) -> None:
    """断言未被 path mismatch 打回。

    只钉"不是 401 path mismatch"而非"必须 200"：这些端点各自还有业务层
    结果（404/空列表等），本用例的判据是认证闸不该拦。
    """
    if resp.status_code == 401:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = resp.text[:120]
        raise AssertionError(f"{label}: 被认证闸打回 401（{detail}）")


def test_q1_single_query_param_passes() -> None:
    """Q-1: 带单个 query 的签名请求不得被 401。"""
    resp = _get("/api/approvals?status=pending")
    _assert_not_path_mismatch(resp, "Q-1 审批页主数据源")


def test_q2_multiple_query_params_pass() -> None:
    """Q-2: 多个 query 参数同样通过。"""
    resp = _get("/api/llm/health?probe=false&x=1")
    _assert_not_path_mismatch(resp, "Q-2 多参数")


def test_q3_repeated_key_query_passes() -> None:
    """Q-3: 多值同名键必须原样透传——dict(query_params) 会塌陷成一个。"""
    resp = _get("/api/approvals?status=pending&status=approved")
    _assert_not_path_mismatch(resp, "Q-3 多值同名键")


def test_q4_no_query_not_regressed() -> None:
    """Q-4: 无 query 的请求不回归（对照组）。"""
    resp = _get("/api/tools/registry")
    _assert_not_path_mismatch(resp, "Q-4 无 query 对照组")


@pytest.mark.parametrize(
    ("url_path", "sign_path", "label"),
    [
        ("/api/approvals?status=approved", "/api/approvals?status=pending", "篡改 query 值"),
        ("/api/approvals?status=pending", "/api/approvals", "签名时无 query，请求时加上"),
        ("/api/approvals", "/api/approvals?status=pending", "签名时有 query，请求时去掉"),
    ],
)
def test_q5_tampered_query_still_401(url_path: str, sign_path: str, label: str) -> None:
    """Q-5: query 与签名不符必须仍 401——防退化成"干脆不比 path"。"""
    resp = _get(url_path, sign_path=sign_path)
    assert resp.status_code == 401, f"Q-5 {label}: 应 401，实际 {resp.status_code}"


def test_q6_tampered_path_still_401() -> None:
    """Q-6: 换 path 搬运已签头必须仍 401（等值断言的主职责）。"""
    resp = _get("/api/tools/registry", sign_path="/api/approvals")
    assert resp.status_code == 401, f"Q-6: 应 401，实际 {resp.status_code}"
