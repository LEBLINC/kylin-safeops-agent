"""RBAC 审批角色校验纯函数（D-3，security 侧）。

只提供"调用者角色能否批准某 approval_role"的确定性判定；认证态（JWT/Token →
调用者角色）的解析与 FastAPI 依赖接线在 api/deps.py，归 API 层（安全层不碰 api/）。

角色口径（与 L 对齐）：内部统一小写 operator / admin。
- admin 可批准 approval_role ∈ {operator, admin} 的 confirm；
- operator 只能批准 approval_role == operator 的 confirm；
- 其余角色（viewer / auditor / 未知值）一律不能批准——失败关闭（fail-closed）。
"""

from __future__ import annotations

#: 角色 → 可批准的 approval_role 集合（失败关闭：不在表内 = 不能批准任何审批）。
_APPROVABLE: dict[str, frozenset[str]] = {
    "operator": frozenset({"operator"}),
    "admin": frozenset({"operator", "admin"}),
}


def can_approve(caller_role: str | None, approval_role: str | None) -> bool:
    """判定 caller_role 是否有权批准要求 approval_role 的 confirm 裁决。

    确定性、无状态、无副作用。任何一侧缺失/未知 → False（失败关闭）。
    大小写不归一：上游（deps.py / 事件层）负责把前端大写 Operator/Admin
    映射为内部小写；本函数收到非小写口径值视为未知角色，拒绝。
    """
    if not caller_role or not approval_role:
        return False
    allowed = _APPROVABLE.get(caller_role)
    if allowed is None:
        return False
    return approval_role in allowed


# ---- L-H2 + L-M4：扩展（commit 2）---------------------------------------

from collections.abc import Iterable  # noqa: E402  # 增量导入（向后兼容原文件）

from backend.app.api.auth import Principal  # noqa: E402


def roles_satisfy(principal: Principal, required: Iterable[str]) -> bool:
    """principal.roles 是否与 required 集合有交集（L-H2 通用 helper）。"""
    return bool(set(required) & principal.roles)


def require_role(role_set: frozenset[str] | set[str]):  # type: ignore[no-untyped-def]
    """L-H2 + L-M4：FastAPI 依赖 — principal.roles 与 role_set 交集为空时返 403。

    用法：
        @router.get(...)
        def endpoint(
            principal: Principal = Depends(require_role({"auditor", "admin"})),
        ): ...

    注意：本文件为 security 纯函数层（deps.py 不能依赖 security 但
    security 可依赖 api deps）。本 helper 仅作**计算工具**暴露；调用方在 router
    里串 ``Depends(verify_token)`` 取得 principal 后再做手动校验或本 helper。
    直接作 Depends() 用法保留以备后端 API 层演进（commit 2 不启用，避免打破
    既有 dev 模式测试）。
    """
    required = frozenset(role_set)

    def _dep(principal: Principal) -> Principal:
        if not roles_satisfy(principal, required):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=403,
                detail=f"role required: {sorted(required)}",
            )
        return principal

    return _dep
