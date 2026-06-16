"""GET /api/auth/whoami — 当前已验证身份（前端身份过渡端点，X 依赖）。

身份来源：
- proxy 模式：反代签名头 → verify_proxy_identity → Principal（user+roles）；无效 → 401。
- dev   模式：放行，返回 dev 占位身份（user="dev"，roles 取裸 X-User-Role 或空）。

只读、只认证；不加角色门槛（与 verify_token 一致）。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header

from backend.app.api.auth import Principal, verify_proxy_identity
from backend.app.api.deps import _AUTH_MODE_ENV, verify_token
from backend.app.api.schemas import WhoamiResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/whoami", response_model=WhoamiResponse)
async def whoami(
    _user: str = Depends(verify_token),
    # 签名头：proxy 模式下复用 verify_proxy_identity 取 Principal（含 roles）。
    # verify_token 已完成认证（保证到这里身份合法）；这里额外取 roles 供前端展示。
    x_auth_user: str | None = Header(default=None),
    x_auth_roles: str | None = Header(default=None),
    x_auth_timestamp: str | None = Header(default=None),
    x_auth_signature: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),  # dev 模式裸头
) -> WhoamiResponse:
    """返回当前已验证身份：user / roles / mode。

    前端无需自建身份状态——直接打此端点知道当前是谁、有哪些角色。
    - proxy 模式：user/roles 来自经过 HMAC 验证的反代签名头（已由 verify_token 完成认证）；
    - dev   模式：user="dev"，roles 取裸 X-User-Role（可伪造，仅联调用）。

    **勿用于授权决策**：角色门槛由审批闸 can_approve 执行；本端点仅展示已验证身份。
    """
    mode = os.environ.get(_AUTH_MODE_ENV, "proxy").strip().lower()

    if mode == "dev":
        roles: list[str] = []
        if x_user_role:
            roles = [x_user_role.strip().lower()]
        return WhoamiResponse(user="dev", roles=roles, mode="dev")

    # proxy 模式：verify_token 已验证合法，Principal 内含 roles，再取一次无额外开销。
    principal: Principal = verify_proxy_identity(  # type: ignore[assignment]
        user=x_auth_user,
        roles=x_auth_roles,
        timestamp=x_auth_timestamp,
        signature=x_auth_signature,
    )
    # verify_token 已确保合法才能到这里；principal 不应为 None，但防御性处理。
    if principal is None:  # pragma: no cover
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="missing or invalid proxy-signed identity")
    return WhoamiResponse(
        user=principal.user,
        roles=sorted(principal.roles),
        mode="proxy",
    )
