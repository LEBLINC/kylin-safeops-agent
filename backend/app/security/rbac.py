"""RBAC 审批角色校验纯函数（D-3，security 侧）。

只提供"调用者角色能否批准某 approval_role"的确定性判定；认证态（JWT/Token →
调用者角色）的解析与 FastAPI 依赖接线在 api/deps.py，归 L（D 不碰 api/）。

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
    大小写不归一：上游（L 的 deps.py / 事件层）负责把前端大写 Operator/Admin
    映射为内部小写；本函数收到非小写口径值视为未知角色，拒绝。
    """
    if not caller_role or not approval_role:
        return False
    allowed = _APPROVABLE.get(caller_role)
    if allowed is None:
        return False
    return approval_role in allowed
