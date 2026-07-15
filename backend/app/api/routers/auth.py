"""GET /api/auth/whoami — 当前已验证身份（前端身份过渡端点，X 依赖）。

身份来源：
- proxy 模式：反代签名头 → verify_proxy_identity → Principal（user+roles）；无效 → 401。
- dev   模式：放行，返回 dev 占位身份（user="dev"，roles 取裸 X-User-Role 或空）。

只读、只认证；不加角色门槛（与 verify_token 语义一致）。

v2 收尾修复：本端点**不再**额外 ``Depends(verify_token)``——proxy 模式下 verify_token
内部会调 verify_proxy_identity 并消费（record）一次性 nonce；若本函数体再用同一 nonce
调第二次 verify_proxy_identity，会撞见 nonce 已被记录而误判为重放 → 恒 401（自锁）。
本函数体的 verify_proxy_identity 调用本身就是 fail-closed 认证闸门，无需叠加。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException

from backend.app.api.auth import Principal, verify_proxy_identity
from backend.app.api.deps import _AUTH_MODE_ENV
from backend.app.api.schemas import WhoamiResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/whoami", response_model=WhoamiResponse)
async def whoami(
    # 签名头：proxy 模式下走 verify_proxy_identity 取 Principal（含 roles），
    # 本调用即认证闸门（fail-closed），故不叠加 Depends(verify_token)（见模块 docstring）。
    x_auth_user: str | None = Header(default=None),
    x_auth_roles: str | None = Header(default=None),
    x_auth_timestamp: str | None = Header(default=None),
    x_auth_signature: str | None = Header(default=None),
    # v2 收尾修复：与 deps.py::verify_token 一致的 4 个 v2 字段（method/path/body_sha/nonce）。
    # 缺失会导致 _canonical 走 v1(3 字段)分支，与反代签的 v2(7 字段)串不匹配 → 恒 401。
    x_auth_method: str | None = Header(default=None, alias="X-Auth-Method"),
    x_auth_path: str | None = Header(default=None, alias="X-Auth-Path"),
    x_auth_body_sha: str | None = Header(default=None, alias="X-Auth-Body-Sha"),
    x_auth_nonce: str | None = Header(default=None, alias="X-Auth-Nonce"),
    x_user_role: str | None = Header(default=None),  # dev 模式裸头
) -> WhoamiResponse:
    """返回当前已验证身份：user / roles / mode。

    前端无需自建身份状态——直接打此端点知道当前是谁、有哪些角色。
    - proxy 模式：user/roles 来自经过 HMAC 验证的反代签名头（本函数体 verify_proxy_identity 认证）；
    - dev   模式：user="dev"，roles 取裸 X-User-Role（可伪造，仅联调用）。

    **勿用于授权决策**：角色门槛由审批闸 can_approve 执行；本端点仅展示已验证身份。
    """
    mode = os.environ.get(_AUTH_MODE_ENV, "proxy").strip().lower()

    if mode == "dev":
        roles: list[str] = []
        if x_user_role:
            roles = [x_user_role.strip().lower()]
        return WhoamiResponse(user="dev", roles=roles, mode="dev")

    # proxy 模式（fail-closed）：本调用即认证闸门；v2 字段必须传入才与反代 v2 签名匹配。
    principal: Principal | None = verify_proxy_identity(
        user=x_auth_user,
        roles=x_auth_roles,
        timestamp=x_auth_timestamp,
        signature=x_auth_signature,
        method=x_auth_method or "",
        path=x_auth_path or "",
        body_sha=x_auth_body_sha or "",
        nonce=x_auth_nonce or "",
    )
    if principal is None:
        raise HTTPException(status_code=401, detail="missing or invalid proxy-signed identity")
    return WhoamiResponse(
        user=principal.user,
        roles=sorted(principal.roles),
        mode="proxy",
    )
