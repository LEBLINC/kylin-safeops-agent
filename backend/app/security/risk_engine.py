"""风险等级工具与参数规则匹配。

重心：结构化 args 的危险值 + ToolSpec.risk。shell 文本规则仅作防御纵深。
本模块无 IO、无状态，供 RuleBasedPolicyEngine.evaluate() 纯函数式调用。
"""

from __future__ import annotations

import re

from backend.app.contracts.tool import RiskLevel
from backend.app.security.normalize import iter_scalar_values
from backend.app.security.policy_rules import PolicyRule

_RISK_RANK: dict[RiskLevel, int] = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4}

# ★ final_risk 死映射表（修正 E）：保证 final_risk 可复算，deny≥R4，confirm+admin≥R3。
# evaluate 使用 _rule_risk_floor + max(spec.risk, floor) 计算 final_risk。
RULE_RISK_FLOOR: dict[tuple[str, str | None], RiskLevel] = {
    ("deny", None): "R4",  # deny 类：最低 R4
    ("deny", ""): "R4",
    ("confirm", "admin"): "R3",  # confirm+admin：最低 R3
    ("confirm", "operator"): "R2",  # confirm+operator：最低 R2
    ("allow", None): "R0",  # allow：不抬 risk
}


def rule_risk_floor(action: str, approval_role: str | None) -> RiskLevel:
    """按规则动作 + 审批角色取 final_risk 最低保障（死映射，可复算）。"""
    key = (action, approval_role or None)
    if key in RULE_RISK_FLOOR:
        return RULE_RISK_FLOOR[key]
    # confirm 但 approval_role 不在已知集 → 保守 R3
    if action == "confirm":
        return "R3"
    if action == "deny":
        return "R4"
    return "R0"


def max_risk(*risks: RiskLevel) -> RiskLevel:
    """取最高风险等级。"""
    if not risks:
        return "R0"
    return max(risks, key=lambda r: _RISK_RANK[r])


def risk_ge(left: RiskLevel, right: RiskLevel) -> bool:
    """left 风险是否 >= right。"""
    return _RISK_RANK[left] >= _RISK_RANK[right]


def rule_matches(rule: PolicyRule, *, tool_name: str, tool_risk: RiskLevel, args: dict) -> bool:
    """判断一条规则是否命中（多条件 AND，同字段列表 OR）。"""
    match = rule.match
    if match.tool_in is not None and tool_name not in match.tool_in:
        return False
    if match.risk_in is not None and tool_risk not in match.risk_in:
        return False
    if match.any_arg_matches is not None:
        values = list(iter_scalar_values(args))
        if not any(re.search(pat, val) for pat in match.any_arg_matches for val in values):
            return False
    return True


def default_decision_for_risk(risk: RiskLevel) -> tuple[str, str | None, str]:
    """按静态风险给默认三态、审批角色、规则 ID。

    内部 approval_role 先遵循 L 口径小写 operator/admin；面向前端的大写 required_role
    在 API/事件层映射（CLAUDE.md §8/§9）。
    """
    if risk in ("R0", "R1"):
        return "allow", None, f"risk:{risk}"
    if risk == "R2":
        return "confirm", "operator", "RISK_R2_OPERATOR_CONFIRM"
    if risk == "R3":
        return "confirm", "admin", "RISK_R3_ADMIN_CONFIRM"
    return "deny", None, "RISK_R4_DENY"


def risk_reason(risk: RiskLevel) -> str:
    """默认风险说明。"""
    return {
        "R0": "只读查询，允许执行。",
        "R1": "轻量诊断，允许执行。",
        "R2": "可逆变更，需要操作员确认。",
        "R3": "影响服务的变更，需要管理员确认。",
        "R4": "高危破坏性操作，禁止执行。",
    }[risk]
