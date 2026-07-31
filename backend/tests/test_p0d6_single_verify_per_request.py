"""P0-D6: 单请求内两个验签依赖自相残杀 —— nonce 一次性把自己锁死。

verify_proxy_identity 验签通过后立即 record(nonce)；同一 nonce 第二次调用
命中 store.seen() → 返回 None。而下列端点各挂了两个都会验签的依赖：

    _user:     str       = Depends(verify_token)             ← 验过，record(nonce)
    principal: Principal = Depends(principal_for_tool_call)  ← seen(nonce)=True → None → 401

⇒ proxy（生产默认）模式下这些端点 100% 401，报文是
"missing or invalid proxy-signed identity"（死在 HMAC 层，与 P0-D1 的
path mismatch 无关）。/api/tools/call 自 P1-6 起即如此，/api/mcp 是 P1-D3 复制过去的。

999 条既有用例一条都没红，因为覆盖盲区正好是三者的交集：
  proxy 模式 × POST × 工具级 RBAC
—— MCP 的用例全在 dev 模式（dev 分支直接从 X-User-Role 造 Principal，
不调 verify_proxy_identity）；P0-D1 的 Q-1..Q-6 在 proxy 模式但只打 GET，
而 GET 路由都只挂一个验签依赖。

本用例刻意做成**自发现**：introspect app.routes 的 dependant 树，把"挂了
≥2 个验签依赖"的路由自动参数化，逐条在 proxy 模式下打一次合规签名请求。
日后任何人再挂第二个验签依赖，用例自动覆盖，不依赖谁记得来加。

刻意**不**写成"断言最多挂一个验签依赖"——那是把症状当根因。
修好之后一条路由挂两个验签依赖本来就该合法。

  V-0 自发现前提：必须真的找到路由（否则 V-1/V-2 退化成空参数化假绿）
  V-1 每条多验签依赖路由在 proxy 模式下不得 401（自动参数化）
  V-2 鉴权不得被缓存放宽：错密钥签名仍必须 401（自动参数化）
  V-3 nonce 跨请求仍是一次性的（防重放语义不得被缓存破坏）
  V-4 失败结果（None）也必须进缓存——V-2 抓不住这个变异，见该用例 docstring
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid

import httpx
import pytest

_SECRET = "d6-guard-secret"

#: 各端点的最小合法请求体（按各自 schema）。新增多验签依赖路由时在此登记；
#: 未登记者用空 JSON 对象兜底——本用例只判"不是 401"，业务层 4xx 不算失败。
_BODY_BY_PATH: dict[str, dict] = {
    "/api/mcp": {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    "/api/tools/call": {"tool": "system.info", "args": {}},
}


def _verifier_names() -> set:
    """deps 模块里所有会调 verify_proxy_identity 的依赖函数。"""
    from backend.app.api import deps

    return {
        deps.verify_token,
        deps.require_proxy_identity,
        deps.principal_for_idor,
        deps.principal_for_tool_call,
    }


def _routes_with_multiple_verifiers() -> list[tuple[str, str]]:
    """递归展开 dependant 树，返回挂了 ≥2 个验签依赖的 (method, path)。

    走 dependant 而非只看函数签名：router 级 dependencies=[...] 也要算进去。
    """
    from backend.app.api.app import create_app

    verifiers = _verifier_names()

    def _walk(dep, acc: list) -> list:  # noqa: ANN001
        for sub in dep.dependencies:
            if sub.call in verifiers:
                acc.append(sub.call.__name__)
            _walk(sub, acc)
        return acc

    out: list[tuple[str, str]] = []
    for route in create_app().routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        if len(_walk(dependant, [])) >= 2:
            for method in sorted(getattr(route, "methods", set()) or set()):
                if method in ("HEAD", "OPTIONS"):
                    continue
                out.append((method, route.path))
    return out


def _signed(method: str, path: str, body: bytes, *, secret: str = _SECRET) -> dict[str, str]:
    user, roles, ts = "admin", "admin", str(int(time.time()))
    body_sha = hashlib.sha256(body).hexdigest()
    nonce = uuid.uuid4().hex
    canonical = f"{user}\n{roles}\n{ts}\n{method}\n{path}\n{body_sha}\n{nonce}"
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Auth-User": user,
        "X-Auth-Roles": roles,
        "X-Auth-Timestamp": ts,
        "X-Auth-Signature": sig,
        "X-Auth-Method": method,
        "X-Auth-Path": path,
        "X-Auth-Body-Sha": body_sha,
        "X-Auth-Nonce": nonce,
        "Content-Type": "application/json",
    }


def _call(method: str, path: str, *, secret: str = _SECRET) -> httpx.Response:
    """proxy 模式下打一次合规签名请求。"""
    from backend.app.api._fakes import build_gateway
    from backend.app.api.app import create_app, get_gateway, lifespan

    body = json.dumps(_BODY_BY_PATH.get(path, {})).encode()

    async def _scenario() -> httpx.Response:
        app = create_app()
        app.dependency_overrides[get_gateway] = build_gateway
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(
                    method, path, content=body, headers=_signed(method, path, body, secret=secret)
                )

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


_MULTI = _routes_with_multiple_verifiers()


def test_v0_discovery_precondition() -> None:
    """V-0 前提：自发现必须真的找到路由，否则 V-1 会退化成空参数化（假绿）。"""
    assert _MULTI, (
        "V-0: 未发现任何多验签依赖路由——自发现逻辑失效，V-1 将无条件通过。"
        "若确已无此类路由，请连同本用例一起删除，不要留一条空转的守门。"
    )


@pytest.mark.parametrize(("method", "path"), _MULTI, ids=[f"{m} {p}" for m, p in _MULTI])
def test_v1_multi_verifier_routes_not_401(method: str, path: str) -> None:
    """V-1: 挂多个验签依赖的路由，合规签名请求不得 401。

    只判"不是 401"：这些端点各自还有业务层结果（200/4xx），
    本用例的判据是认证链不该自相残杀。
    """
    resp = _call(method, path)
    assert resp.status_code != 401, (
        f"V-1: {method} {path} 合规签名请求被 401——"
        f"单请求内多次验签，nonce 一次性把自己锁死：{resp.text[:160]}"
    )


@pytest.mark.parametrize(("method", "path"), _MULTI, ids=[f"{m} {p}" for m, p in _MULTI])
def test_v2_bad_signature_still_401(method: str, path: str) -> None:
    """V-2: 缓存不得放宽鉴权——错密钥签的请求仍必须 401。

    这条钉的是"连失败结果一起缓存"不能写成"失败就不缓存"，
    更不能写成"缓存里没有就放行"。
    """
    resp = _call(method, path, secret="wrong-secret-not-the-real-one")
    assert (
        resp.status_code == 401
    ), f"V-2: {method} {path} 用错密钥签名却未被拒（{resp.status_code}）——鉴权被缓存放宽"


def test_v4_failure_is_cached_too() -> None:
    """V-4: 失败结果（None）也必须进缓存，否则失败路径每次重算。

    为什么单靠 V-2 抓不住："只缓存成功"这个变异下，错签名请求的**第一个**
    依赖就 raise 401，第二个依赖根本不会执行——两种实现的外部表现完全一样
    （已实测：该变异下 V-1/V-2 全绿）。故必须直接验缓存契约本身：
    调两次 _verify_once，第二次不得再进 verify_proxy_identity。

    这条契约的实际意义：日后若有人把依赖改成"失败不立即 raise、继续往下走"
    （例如做成可选鉴权），只缓存成功就会让第二个依赖撞上 nonce 的 seen()，
    P0-D6 原地复活。缓存语义应当自洽，不能依赖调用方恰好提前 raise。
    """
    from starlette.requests import Request

    from backend.app.api import deps

    calls: list[int] = []

    def _counting_verify(**kwargs):  # noqa: ANN003, ANN202
        calls.append(1)
        return None  # 恒失败

    async def _empty_receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/x",
            "query_string": b"",
            "headers": [],
        },
        receive=_empty_receive,
    )

    original = deps.verify_proxy_identity
    deps.verify_proxy_identity = _counting_verify  # type: ignore[assignment]
    try:
        kwargs = {
            "user": "u",
            "roles": "operator",
            "timestamp": "1",
            "signature": "bad",
            "method": "POST",
            "path": "/api/x",
            "body_sha": "x",
            "nonce": "n",
        }
        first = asyncio.run(deps._verify_once(request, **kwargs))  # type: ignore[arg-type]
        second = asyncio.run(deps._verify_once(request, **kwargs))  # type: ignore[arg-type]
    finally:
        deps.verify_proxy_identity = original  # type: ignore[assignment]

    assert first is None and second is None, "V-4: 失败结果应稳定为 None"
    assert len(calls) == 1, (
        f"V-4: verify_proxy_identity 被调了 {len(calls)} 次——失败结果没进缓存，"
        f"第二个依赖会重算并撞上 nonce 的 seen()"
    )


def test_v3_nonce_still_single_use_across_requests() -> None:
    """V-3: 缓存是 per-request 的，跨请求的 nonce 一次性防重放不得被破坏。

    直接验底层：同一组签名参数连调两次 verify_proxy_identity，
    第二次必须 None（缓存挂在 request.state，不影响这一层）。
    """
    from backend.app.api.auth import _reset_nonce_store_for_tests, verify_proxy_identity

    old_secret = os.environ.get("KYLIN_PROXY_AUTH_SECRET")
    os.environ["KYLIN_PROXY_AUTH_SECRET"] = _SECRET
    _reset_nonce_store_for_tests()
    try:
        user, roles, ts = "admin", "admin", str(int(time.time()))
        body_sha = hashlib.sha256(b"").hexdigest()
        nonce = "v3-fixed-nonce"
        canonical = f"{user}\n{roles}\n{ts}\nGET\n/api/x\n{body_sha}\n{nonce}"
        sig = hmac.new(_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        kwargs = {
            "user": user,
            "roles": roles,
            "timestamp": ts,
            "signature": sig,
            "method": "GET",
            "path": "/api/x",
            "body_sha": body_sha,
            "nonce": nonce,
        }
        first = verify_proxy_identity(**kwargs)  # type: ignore[arg-type]
        second = verify_proxy_identity(**kwargs)  # type: ignore[arg-type]
    finally:
        _reset_nonce_store_for_tests()
        if old_secret is None:
            os.environ.pop("KYLIN_PROXY_AUTH_SECRET", None)
        else:
            os.environ["KYLIN_PROXY_AUTH_SECRET"] = old_secret

    assert first is not None, "V-3 前提：首次验签应通过"
    assert second is None, "V-3: 同一 nonce 第二次仍通过——跨请求防重放被破坏"
