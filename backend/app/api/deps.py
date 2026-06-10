"""API 层共享依赖（FastAPI Depends）。

认证占位 + 全局单例访问。

安全要求（B/S 暴露端点红线）：
- verify_token 是所有端点的认证入口，当前为联调占位（永远放行）。
- 启动日志 + 响应头显式标注"认证未接入，仅限内网/联调"。
- TODO(BLOCKED-ON-D): 接 D 的 RBAC 模块后替换为真实 JWT/Token 校验。
"""

from __future__ import annotations

import logging

from fastapi import Header

logger = logging.getLogger(__name__)

# ============================================================
# 认证占位（铁律：绝不静默无防护）
# ============================================================

_AUTH_WARNING = "认证未接入，仅限内网/联调环境使用。" "TODO(BLOCKED-ON-D): 接 D 的 RBAC 校验。"


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


async def verify_approval_role(
    authorization: str | None = Header(default=None),
) -> str:
    """审批端点专用：校验调用者是否有审批权限。

    当前占位放行。正式环境须校验 approval_role 匹配。

    WARNING: 审批回传端点是人工确认闸入口，绝不可裸暴露。
    TODO(BLOCKED-ON-D): 接 D 的 RBAC 校验 approval_role。
    """
    # TODO(BLOCKED-ON-D): 接 D 的 RBAC 校验 approval_role
    # user = await d_rbac.verify(authorization)
    # if "approver" not in user.roles:
    #     raise HTTPException(status_code=403, detail="insufficient role")
    logger.debug(
        "verify_approval_role: 审批角色占位放行 (authorization=%s)",
        authorization,
    )
    return "anonymous"
