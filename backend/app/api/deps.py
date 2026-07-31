"""API 层共享依赖（FastAPI Depends）。

全量端点认证（mode-aware）+ 全局单例访问。

安全要求（B/S 暴露端点红线）：
- verify_token 是所有端点的认证入口：proxy 模式要求反代签名身份（fail-closed 401），
  dev 模式联调放行；默认 proxy（安全兜底）。
- verify_token 只做认证（确认存在已验证身份即可）；角色授权仍归审批闸 can_approve，
  此处不加角色门槛。
- 启动日志显式标注认证姿态（proxy 全量签名身份 / dev 联调放行）。
"""

from __future__ import annotations

import hashlib
import logging
import os

from fastapi import Header, HTTPException, Request

from backend.app.api.auth import Principal, verify_proxy_identity

logger = logging.getLogger(__name__)

# ============================================================
# 认证（铁律：绝不静默无防护；proxy 默认 fail-closed）
# ============================================================

_AUTH_WARNING = (
    "认证姿态：proxy 模式全量端点要求反代签名身份（fail-closed 401）/ "
    "dev 模式联调放行（演示态，角色可伪造，严禁用于生产）。"
)

#: 认证模式环境变量名 + 默认值。proxy=生产（强制签名头校验，fail-closed）；
#: dev=联调态（接受裸 X-User-Role，不验签，大声告警）。默认 proxy = 安全兜底。
_AUTH_MODE_ENV = "KYLIN_AUTH_MODE"


def _auth_mode() -> str:
    """读取认证模式（与 require_proxy_identity 同口径）；默认 proxy = 安全兜底。"""
    return os.environ.get(_AUTH_MODE_ENV, "proxy").strip().lower()


#: request.state 上缓存验签结果的键。值是 (入参指纹, Principal | None) 二元组——
#: 用元组包一层是为了把"验过且失败(None)"与"还没验"区分开；
#: 带上入参指纹是为了让缓存**以凭据为键**而不只是以请求为键（O-1）。
_VERIFY_CACHE_ATTR = "_kylin_proxy_identity"


async def _verify_once(
    request: Request,
    *,
    user: str | None,
    roles: str | None,
    timestamp: str | None,
    signature: str | None,
    method: str | None,
    path: str | None,
    body_sha: str | None,
    nonce: str | None,
) -> Principal | None:
    """每请求只做一次 HMAC 验签，结果（含失败的 None）缓存在 request.state。

    P0-D6：nonce 是一次性的——verify_proxy_identity 验签通过后即 record(nonce)，
    同一 nonce 第二次调用命中 seen() 直接返回 None。而 /api/tools/call 与
    /api/mcp 各挂了两个都会验签的依赖（verify_token + principal_for_tool_call），
    第二个必然撞上自己刚 record 的 nonce → 生产模式下这两条端点 100% 401。

    缓存必须连 None 一起缓存：只缓存成功结果的话，失败路径每次重算，
    第二个依赖照样走到 seen() 判定，等于没修。

    跨请求语义不变：缓存挂在 request.state，请求结束即销毁，
    nonce 的一次性防重放对**不同请求**照常生效。

    O-1：缓存**以入参指纹为键**，不只以请求为键。当前四个依赖都从同一 request
    读同一组头，入参必然相同——但那是巧合不是不变量。若日后有依赖改从别处取
    凭据（如某个头的备用别名、或先做一次归一化），只按 request 缓存就会把
    A 凭据的裁决结果返回给 B 凭据的调用方，等于用错误的身份授权。
    带指纹后：同凭据 → 命中缓存（P0-D6 的修复不变）；异凭据 → 各自真验一次
    （语义正确；若两者共用同一 nonce，第二次本就该按重放拒掉）。
    """
    key = (user, roles, timestamp, signature, method, path, body_sha, nonce)
    cached = getattr(request.state, _VERIFY_CACHE_ATTR, None)
    if cached is not None and cached[0] == key:
        return cached[1]
    principal = verify_proxy_identity(
        user=user,
        roles=roles,
        timestamp=timestamp,
        signature=signature,
        method=method or "",
        path=path or "",
        body_sha=body_sha or "",
        nonce=nonce or "",
    )
    setattr(request.state, _VERIFY_CACHE_ATTR, (key, principal))
    return principal


async def _assert_request_binding(
    request: Request,
    x_auth_method: str | None,
    x_auth_path: str | None,
    x_auth_body_sha: str | None,
) -> None:
    """P1-5 等值断言：签名头声明的 method/path/body_sha 必须与实际请求匹配。

    全量签名头防中途篡改的语义要求此检验：当前实现只验证 HMAC 本身（签名链合法），
    但 method/path/body_sha 均取自请求头——反代签名的是头里的值，而不是真实请求的值。
    攻击者可把一次已签请求的全部 8 个头搬到任意特权调用上（replaying signed headers
    to a different endpoint/method/body），完全绕过"防中途篡改"语义。

    仅在 proxy 模式且三个头均非空时校验（dev 联调模式无签名头）。
    """
    if _auth_mode() != "proxy":
        return
    actual_method = request.method.upper()
    # 必须与签名方口径字节级一致：proxy.py 把 f"/{path}?{query}" 写进 X-Auth-Path
    # （见 deploy/proxy/proxy.py 的 full_path 构造）。此处若只取 request.url.path，
    # 带 query 的请求两边永远不等 → 生产模式下审批页/工具历史/策略命中等全部 401；
    # 反向也错：签名时无 query、请求时补一个 query，两边又都等于裸 path → 篡改放行。
    # 用 raw scope["query_string"] 而非 dict(query_params)：后者会把多值同名键
    # 塌陷（?a=1&a=2 只剩一个）并可能改序，重编码差异会造出一批看似随机的 401。
    raw_query = request.scope.get("query_string", b"")
    if isinstance(raw_query, bytes):
        raw_query = raw_query.decode("latin-1")
    actual_path = request.url.path + (f"?{raw_query}" if raw_query else "")
    actual_body = await request.body()
    actual_body_sha = hashlib.sha256(actual_body).hexdigest()

    if x_auth_method and x_auth_method.upper() != actual_method:
        raise HTTPException(status_code=401, detail="proxy signature: method mismatch")
    if x_auth_path and x_auth_path != actual_path:
        raise HTTPException(status_code=401, detail="proxy signature: path mismatch")
    if x_auth_body_sha and x_auth_body_sha != actual_body_sha:
        raise HTTPException(status_code=401, detail="proxy signature: body_sha mismatch")


async def verify_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_auth_user: str | None = Header(default=None),
    x_auth_roles: str | None = Header(default=None),
    x_auth_timestamp: str | None = Header(default=None),
    x_auth_signature: str | None = Header(default=None),
    x_auth_method: str | None = Header(default=None, alias="X-Auth-Method"),
    x_auth_path: str | None = Header(default=None, alias="X-Auth-Path"),
    x_auth_body_sha: str | None = Header(default=None, alias="X-Auth-Body-Sha"),
    x_auth_nonce: str | None = Header(default=None, alias="X-Auth-Nonce"),
) -> str:
    """全量端点认证依赖（mode-aware）：所有端点必经此依赖。

    按 ``KYLIN_AUTH_MODE`` 分支（默认 ``proxy`` = 安全兜底）：
    - ``proxy``（生产）：从 4 个反代签名头 verify_proxy_identity；缺失/非法 → 401（fail-closed）；
      合法 → 返回已验证用户名 ``p.user``。
    - ``dev``（联调）：放行，返回 ``"dev"``（不要求签名头；联调用）。

    本依赖**只做认证**（确认存在已验证身份），不取角色、不加授权门槛——
    角色授权仍归审批闸 ``require_proxy_identity`` + ``can_approve``，二者并存。
    返回 ``str`` 以保持各端点 ``Depends(verify_token)`` 写法不变。
    """
    mode = _auth_mode()
    if mode == "dev":
        # dev 放行：告警勿每请求刷屏（lifespan 已有全局 warning），用 debug。
        logger.debug("verify_token: dev 模式联调放行（不要求签名身份）")
        return "dev"

    # proxy 模式（默认，fail-closed）：复用 auth.py 验签，不取角色。
    # D 阻断修复: 反代真接 v2 走通 (method/path/body_sha/nonce 入签).
    principal = await _verify_once(
        request,
        user=x_auth_user,
        roles=x_auth_roles,
        timestamp=x_auth_timestamp,
        signature=x_auth_signature,
        method=x_auth_method,
        path=x_auth_path,
        body_sha=x_auth_body_sha,
        nonce=x_auth_nonce,
    )
    if principal is None:
        raise HTTPException(status_code=401, detail="missing or invalid proxy-signed identity")
    await _assert_request_binding(request, x_auth_method, x_auth_path, x_auth_body_sha)
    return principal.user


async def require_proxy_identity(
    request: Request,
    x_auth_user: str | None = Header(default=None),
    x_auth_roles: str | None = Header(default=None),
    x_auth_timestamp: str | None = Header(default=None),
    x_auth_signature: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
    x_auth_method: str | None = Header(default=None, alias="X-Auth-Method"),
    x_auth_path: str | None = Header(default=None, alias="X-Auth-Path"),
    x_auth_body_sha: str | None = Header(default=None, alias="X-Auth-Body-Sha"),
    x_auth_nonce: str | None = Header(default=None, alias="X-Auth-Nonce"),
) -> Principal:
    """审批端点专用认证依赖：返回经验证的 Principal；非法 → 401（fail-closed）。

    按 ``KYLIN_AUTH_MODE`` 分支（默认 ``proxy`` = 安全兜底）：
    - ``proxy``（生产）：从 4 个签名头 verify_proxy_identity，非法/缺失 → 401；合法 → Principal。
    - ``dev``（联调）：接受裸 ``X-User-Role``（归一小写）不验签，**每次大声告警**；缺角色头 → 401。
      dev 模式仅为不切断 X 前端审批联调（dev 无反代、签不出 HMAC）；**严禁用于生产**。

    本依赖只接**审批授权来源**，不等于全量端点身份认证（其余端点仍内网态 verify_token）。
    """
    mode = os.environ.get(_AUTH_MODE_ENV, "proxy").strip().lower()
    if mode == "dev":
        logger.warning("⚠ DEV 认证模式：审批角色取自裸 X-User-Role、可伪造，严禁用于生产！")
        if not x_user_role:
            raise HTTPException(
                status_code=401, detail="missing X-User-Role (dev auth mode requires a role)"
            )
        return Principal(user="dev", roles=frozenset({x_user_role.strip().lower()}))

    # proxy 模式（默认，fail-closed）
    # D 阻断修复: 反代真接 v2 走通 (method/path/body_sha/nonce 入签).
    principal = await _verify_once(
        request,
        user=x_auth_user,
        roles=x_auth_roles,
        timestamp=x_auth_timestamp,
        signature=x_auth_signature,
        method=x_auth_method,
        path=x_auth_path,
        body_sha=x_auth_body_sha,
        nonce=x_auth_nonce,
    )
    if principal is None:
        raise HTTPException(status_code=401, detail="missing or invalid proxy-signed identity")
    await _assert_request_binding(request, x_auth_method, x_auth_path, x_auth_body_sha)
    return principal


async def principal_for_idor(
    request: Request,
    x_auth_user: str | None = Header(default=None),
    x_auth_roles: str | None = Header(default=None),
    x_auth_timestamp: str | None = Header(default=None),
    x_auth_signature: str | None = Header(default=None),
    x_auth_method: str | None = Header(default=None, alias="X-Auth-Method"),
    x_auth_path: str | None = Header(default=None, alias="X-Auth-Path"),
    x_auth_body_sha: str | None = Header(default=None, alias="X-Auth-Body-Sha"),
    x_auth_nonce: str | None = Header(default=None, alias="X-Auth-Nonce"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> Principal:
    """L-H1 IDOR 校验专用：从已验证身份派生 Principal（含 roles）。

    dev: user="dev", roles = header X-User-Role(env KYLIN_TEST_X_USER_ROLE 兜底)（不验签，仅联调）。
    proxy: v2 收尾修复 — 镜像 whoami/require_proxy_identity，直接调 verify_proxy_identity
        取含 roles 的完整 Principal（fail-closed 401）；不再从裸 X-User-Role 取角色
        （反代已剥除该头，此前恒空——principal.roles 恒空 → IDOR is_admin 恒 False）。
        本调用即认证闸门，不叠加 Depends(verify_token)（避免二次消费一次性 nonce，见
        routers/auth.py::whoami 同一教训）。
    """
    mode = _auth_mode()
    if mode == "dev":
        roles: frozenset[str] = frozenset()
        raw: str = x_user_role if x_user_role else os.environ.get("KYLIN_TEST_X_USER_ROLE", "")
        if raw:
            roles = frozenset({r.strip().lower() for r in raw.split(",") if r.strip()})
        return Principal(user="dev", roles=roles)

    principal = await _verify_once(
        request,
        user=x_auth_user,
        roles=x_auth_roles,
        timestamp=x_auth_timestamp,
        signature=x_auth_signature,
        method=x_auth_method,
        path=x_auth_path,
        body_sha=x_auth_body_sha,
        nonce=x_auth_nonce,
    )
    if principal is None:
        raise HTTPException(status_code=401, detail="missing or invalid proxy-signed identity")
    await _assert_request_binding(request, x_auth_method, x_auth_path, x_auth_body_sha)
    return principal


async def principal_for_tool_call(
    request: Request,
    x_auth_user: str | None = Header(default=None),
    x_auth_roles: str | None = Header(default=None),
    x_auth_timestamp: str | None = Header(default=None),
    x_auth_signature: str | None = Header(default=None),
    x_auth_method: str | None = Header(default=None, alias="X-Auth-Method"),
    x_auth_path: str | None = Header(default=None, alias="X-Auth-Path"),
    x_auth_body_sha: str | None = Header(default=None, alias="X-Auth-Body-Sha"),
    x_auth_nonce: str | None = Header(default=None, alias="X-Auth-Nonce"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> Principal:
    """P1-6 工具级 RBAC 专用：取含 roles 的 Principal，供 /api/tools/call 裁决。

    与 principal_for_idor 同款实现（dev 取裸头 / proxy 验签）。单独立一个而非
    复用，是为了让"谁在做工具级 RBAC"在路由签名上直接可见；也避免改
    verify_token 的返回签名波及所有挂它的端点。
    """
    mode = _auth_mode()
    if mode == "dev":
        roles: frozenset[str] = frozenset()
        raw: str = x_user_role if x_user_role else os.environ.get("KYLIN_TEST_X_USER_ROLE", "")
        if raw:
            roles = frozenset({r.strip().lower() for r in raw.split(",") if r.strip()})
        return Principal(user="dev", roles=roles)

    principal = await _verify_once(
        request,
        user=x_auth_user,
        roles=x_auth_roles,
        timestamp=x_auth_timestamp,
        signature=x_auth_signature,
        method=x_auth_method,
        path=x_auth_path,
        body_sha=x_auth_body_sha,
        nonce=x_auth_nonce,
    )
    if principal is None:
        raise HTTPException(status_code=401, detail="missing or invalid proxy-signed identity")
    await _assert_request_binding(request, x_auth_method, x_auth_path, x_auth_body_sha)
    return principal
