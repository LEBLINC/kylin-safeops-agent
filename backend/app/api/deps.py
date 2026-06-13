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
    x_user_role: str | None = Header(default=None),
) -> str | None:
    """审批端点专用：解析调用者角色（演示态），归一为内部小写返回。

    人工确认闸的**授权**入口：从请求头 ``X-User-Role`` 取调用者角色（前端演示态现用构建期
    env 角色），大小写归一为内部小写（``Admin``→``admin`` / ``Operator``→``operator``）。
    未知/拼错/缺失角色保留归一后原值或 None，交给下游 ``can_approve`` 失败关闭（fail-closed）。

    返回的是 caller_role（替换原"永远放行"占位），由 approvals.resume 接 can_approve 强制。

    WARNING: 本步只接**审批授权**，不等于接入了**身份认证**——调用者声称的角色未经任何
    可信凭证验证（演示态）。"认证未接入"全局告警仍然有效。
    TODO(待 L 拍板): 真实认证源（JWT/Token/标准 header）与角色可信来源待定。
    """
    if x_user_role is None:
        logger.debug("verify_approval_role: 缺角色头 → None（下游 can_approve fail-closed）")
        return None
    caller_role = x_user_role.strip().lower()
    logger.debug("verify_approval_role: 演示态角色头归一 caller_role=%s", caller_role)
    return caller_role or None
