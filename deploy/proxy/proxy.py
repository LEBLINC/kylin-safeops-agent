"""
Signature reverse proxy sidecar: client -> sidecar(public) -> app(127.0.0.1:8000)
- LDAP auth via deploy.sso.ldap_client.LdapClient (mock/real modes)
- Strips client-forged X-Auth-* headers
- Injects HMAC-SHA256 signed 4 identity headers
- SSE passthrough (no buffering)
"""

import hashlib
import hmac
import os
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from deploy.sso.ldap_client import LdapClient

app = FastAPI()
ldap_client = LdapClient()
SECRET = os.environ["KYLIN_PROXY_AUTH_SECRET"]
UPSTREAM = os.environ.get("KYLIN_UPSTREAM", "http://127.0.0.1:8000")


def sign(user: str, roles: str, ts: str) -> str:
    canonical = f"{user}\n{roles}\n{ts}"
    return hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()


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


STRIP_HEADERS = {
    "x-auth-user",
    "x-auth-roles",
    "x-auth-timestamp",
    "x-auth-signature",
    "x-user-role",
}


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
    headers.update(
        {
            "X-Auth-User": user,
            "X-Auth-Roles": roles,
            "X-Auth-Timestamp": ts,
            "X-Auth-Signature": sign(user, roles, ts),
        }
    )
    is_sse = "text/event-stream" in request.headers.get("accept", "")
    body = await request.body()
    async with httpx.AsyncClient(timeout=None) as client:
        req = client.build_request(
            request.method,
            f"{UPSTREAM}/{path}",
            headers=headers,
            content=body,
            params=dict(request.query_params),
        )
        resp = await client.send(req, stream=True)
        if is_sse:
            return StreamingResponse(
                _sse_heartbeat(resp.aiter_bytes()),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                background=BackgroundTask(resp.aclose),
            )
        body_bytes = b"".join([chunk async for chunk in resp.aiter_bytes()])
        await resp.aclose()
        return StreamingResponse(
            iter([body_bytes]),
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )
