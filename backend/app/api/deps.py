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

import logging
import os

from fastapi import Header, HTTPException

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


async def verify_token(
    authorization: str | None = Header(default=None),
    x_auth_user: str | None = Header(default=None),
    x_auth_roles: str | None = Header(default=None),
    x_auth_timestamp: str | None = Header(default=None),
    x_auth_signature: str | None = Header(default=None),
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
    principal = verify_proxy_identity(
        user=x_auth_user,
        roles=x_auth_roles,
        timestamp=x_auth_timestamp,
        signature=x_auth_signature,
    )
    if principal is None:
        raise HTTPException(status_code=401, detail="missing or invalid proxy-signed identity")
    return principal.user


async def require_proxy_identity(
    x_auth_user: str | None = Header(default=None),
    x_auth_roles: str | None = Header(default=None),
    x_auth_timestamp: str | None = Header(default=None),
    x_auth_signature: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
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
    principal = verify_proxy_identity(
        user=x_auth_user,
        roles=x_auth_roles,
        timestamp=x_auth_timestamp,
        signature=x_auth_signature,
    )
    if principal is None:
        raise HTTPException(status_code=401, detail="missing or invalid proxy-signed identity")
    return principal
