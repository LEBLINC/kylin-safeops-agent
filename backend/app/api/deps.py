"""API 层共享依赖（FastAPI Depends）。

认证占位 + 全局单例访问。

安全要求（B/S 暴露端点红线）：
- verify_token 是所有端点的认证入口，当前为联调占位（永远放行）。
- 启动日志 + 响应头显式标注"认证未接入，仅限内网/联调"。
- TODO(BLOCKED-ON-D): 接 D 的 RBAC 模块后替换为真实 JWT/Token 校验。
"""

from __future__ import annotations

import logging
import os

from fastapi import Header, HTTPException

from backend.app.api.auth import Principal, verify_proxy_identity

logger = logging.getLogger(__name__)

# ============================================================
# 认证占位（铁律：绝不静默无防护）
# ============================================================

_AUTH_WARNING = (
    "审批闸 proxy 模式要求反代签名身份 / dev 模式演示态（角色可伪造，仅联调）；"
    "其余端点仍内网 only，全量端点认证待后续。"
)

#: 认证模式环境变量名 + 默认值。proxy=生产（强制签名头校验，fail-closed）；
#: dev=联调态（接受裸 X-User-Role，不验签，大声告警）。默认 proxy = 安全兜底。
_AUTH_MODE_ENV = "KYLIN_AUTH_MODE"


async def verify_token(
    authorization: str | None = Header(default=None),
) -> str:
    """认证依赖占位：所有端点必须经过此依赖。

    当前逻辑：永远放行，返回伪用户标识 "anonymous"。
    正式环境由 D 的 RBAC 模块替换。

    WARNING: 本函数当前不做实际校验，仅为结构占位。
    """
    # TODO(BLOCKED-ON-D): 接 D 的 JWT/Token 校验
    # if not authorization:
    #     raise HTTPException(status_code=401, detail="missing token")
    # user = await d_rbac.verify(authorization)
    logger.debug("verify_token: 认证占位放行 (authorization=%s)", authorization)
    return "anonymous"


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
