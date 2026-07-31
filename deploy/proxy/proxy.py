"""
Signature reverse proxy sidecar: client -> sidecar(public) -> app(127.0.0.1:8000)
- LDAP auth via deploy.sso.ldap_client.LdapClient (mock/real modes)
- Strips client-forged X-Auth-* headers
- Injects HMAC-SHA256 signed 4 identity headers
- SSE passthrough (no buffering)

B2 (架构审计 154f767)：ADR-0004 第三道保险原只落在 backend/app/api/app.py 的
lifespan fail-fast——但那是 app 进程，从不实例化 LdapClient，真正读
KYLIN_LDAP_MOCK 并可能静默切 mock 的是本 proxy 进程。app.py 那道保留做冗余
（防运维只查 app 日志误判"已拦"），本模块加第四道：proxy 进程启动（模块 import
期）即检查，mock=true 时 SystemExit 拒绝启动（fail-fast，systemd 立即 failed）。
"""

import os
import sys
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from deploy.proxy._sign import STRIP_HEADERS, sign
from deploy.sso.ldap_client import LdapClient


def _fail_fast_if_mock_in_production() -> None:
    """ADR-0004 第四道保险：proxy 进程 mock=true 时拒绝启动（fail-fast）。

    与 backend/app/api/app.py 的 lifespan fail-fast 同一决策（ADR-0004），
    但落在真跑 LdapClient 的进程——app.py 那道守不到这里（app 进程不含
    LdapClient 实例化）。KYLIN_PROXY_ALLOW_MOCK=true 仅供本地联调/CI 单测
    显式 opt-out（模块 import 时机太早，无法用 pytest monkeypatch 覆盖，
    需要真实环境变量放行才能测试模块本身不炸）。
    """
    if os.environ.get("KYLIN_PROXY_ALLOW_MOCK", "").strip().lower() == "true":
        return
    if os.environ.get("KYLIN_LDAP_MOCK", "").strip().lower() == "true":
        sys.stderr.write(
            "ADR-0004: proxy 拒绝启动——KYLIN_LDAP_MOCK=true 仅允许 demo/单测。"
            "生产必须 KYLIN_LDAP_MOCK=false + 真 LDAP；"
            "联调需要 mock 时显式设 KYLIN_PROXY_ALLOW_MOCK=true。\n"
        )
        raise SystemExit(1)


_fail_fast_if_mock_in_production()

app = FastAPI()
ldap_client = LdapClient()
UPSTREAM = os.environ.get("KYLIN_UPSTREAM", "http://127.0.0.1:8000")


async def _sse_heartbeat(source, interval: int = 30):
    import asyncio

    interval = int(os.environ.get("KYLIN_SSE_HEARTBEAT_INTERVAL", interval))
    while True:
        try:
            chunk = await asyncio.wait_for(source.__anext__(), timeout=interval)
            yield chunk
        except asyncio.TimeoutError:
            yield b": keepalive\n\n"
        except StopAsyncIteration:
            break


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_route(request: Request, path: str):
    import base64

    from fastapi.responses import Response as FastAPIResponse

    auth = request.headers.get("authorization", "")
    if not auth.startswith("Basic "):
        return FastAPIResponse(
            status_code=401,
            content="authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Kylin SafeOps"'},
        )
    try:
        decoded = base64.b64decode(auth[6:]).decode()
        username, password = decoded.split(":", 1)
    except Exception:
        return FastAPIResponse(
            status_code=401,
            content="invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="Kylin SafeOps"'},
        )

    if not ldap_client.authenticate(username, password):
        return FastAPIResponse(
            status_code=403,
            content="authentication failed",
            headers={"WWW-Authenticate": 'Basic realm="Kylin SafeOps"'},
        )

    ldap_user = ldap_client.get_user(username)
    if ldap_user is None:
        return FastAPIResponse(
            status_code=403,
            content="user not found in LDAP directory",
            headers={"WWW-Authenticate": 'Basic realm="Kylin SafeOps"'},
        )

    user = ldap_user.username
    roles = ",".join(ldap_user.roles)

    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in STRIP_HEADERS and k.lower() != "host"
    }
    ts = str(int(time.time()))
    # A1.3 v2 签名: method/path/body_sha/nonce 防中途篡改+防重放
    body = await request.body()
    import hashlib as _hb
    import uuid as _u

    body_sha = _hb.sha256(body or b"").hexdigest()
    nonce = _u.uuid4().hex
    full_path = f"/{path}"
    if request.url.query:
        full_path = f"{full_path}?{request.url.query}"
    headers.update(
        {
            "X-Auth-User": user,
            "X-Auth-Roles": roles,
            "X-Auth-Timestamp": ts,
            "X-Auth-Signature": sign(user, roles, ts, request.method, full_path, body_sha, nonce),
            "X-Auth-Method": request.method,
            "X-Auth-Path": full_path,
            "X-Auth-Body-Sha": body_sha,
            "X-Auth-Nonce": nonce,
        }
    )
    is_sse = "text/event-stream" in request.headers.get("accept", "")
    # 之七十五 H-9：client 不能用 async with——StreamingResponse 的 body 是在本函数
    # return 之后才被 ASGI 层消费的，async with 会在 return 时就关掉 client，
    # 流还没读完连接就断。改为手工持有，由 BackgroundTask 在响应发完后依次
    # aclose(resp) → aclose(client)（顺序不能颠倒：先关 client 会掐断 resp 的流）。
    client = httpx.AsyncClient(timeout=None)
    try:
        # URL 直接带上原始 query（full_path 已含 ?query），不用 params=：
        # params=dict(request.query_params) 会把多值同名键塌陷（?a=1&a=2 只剩一个），
        # httpx 还会重新编码、可能改序——而 X-Auth-Path 签的是原始串，
        # 重编码差异会让上游等值断言看到一批"看似随机"的 401。原样透传语义最直白。
        req = client.build_request(
            request.method,
            f"{UPSTREAM}{full_path}",
            headers=headers,
            content=body,
        )
        resp = await client.send(req, stream=True)
    except BaseException:
        await client.aclose()
        raise

    async def _release() -> None:
        await resp.aclose()
        await client.aclose()

    if is_sse:
        return StreamingResponse(
            _sse_heartbeat(resp.aiter_bytes()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            background=BackgroundTask(_release),
        )
    # H-9：非 SSE 也流式透传，不再 b"".join 整体缓冲。
    # 原实现把整个响应读进内存才回发，大响应（审计导出、工具调用列表）内存翻倍
    # 且首字节延迟 == 上游总耗时；透传后内存恒定、首字节即到即发。
    return StreamingResponse(
        resp.aiter_bytes(),
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
        background=BackgroundTask(_release),
    )
