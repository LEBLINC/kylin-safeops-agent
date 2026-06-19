"""
Signature reverse proxy sidecar: client -> sidecar(public) -> app(127.0.0.1:8000)
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

app = FastAPI()
SECRET = os.environ["KYLIN_PROXY_AUTH_SECRET"]
UPSTREAM = os.environ.get("KYLIN_UPSTREAM", "http://127.0.0.1:8000")

USER_ROLE_MAP = {
    "admin": "admin,operator",
    "operator": "operator",
    "viewer": "viewer",
    "auditor": "auditor",
}


def sign(user: str, roles: str, ts: str) -> str:
    canonical = f"{user}\n{roles}\n{ts}"
    return hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()


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
        u, _ = decoded.split(":", 1)
        user, roles = u, USER_ROLE_MAP.get(u, "viewer")
    except Exception:
        return FastAPIResponse(
            status_code=401,
            content="invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="Kylin SafeOps"'},
        )
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
                resp.aiter_bytes(),
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