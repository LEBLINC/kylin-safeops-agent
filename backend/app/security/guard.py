"""规则驱动 PolicyEngine 实现（D）。

核心校准：主力是结构化参数危险值 + ProtectedPaths + ToolSpec.risk；
CMD001-003 等 shell 文本匹配仅作防御纵深。

构造签名：RuleBasedPolicyEngine(policy: PolicySet, registry: ToolRegistry)
  - policy 在前（L 的接线点 policy=... 关键字注入）。
  - registry 注入必须与 gateway 使用同一实例，否则注册表漂移。
  - 导出 PolicyEngine = RuleBasedPolicyEngine 别名，L 直接 import PolicyEngine。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import Decision, PolicyVerdict
from backend.app.contracts.tool import RiskLevel, ToolSpec
from backend.app.mcp.registry import ToolRegistry
from backend.app.security.path_policy import PathFinding, classify_paths
from backend.app.security.policy_loader import DEFAULT_POLICY
from backend.app.security.policy_rules import PolicyRule, PolicySet
from backend.app.security.risk_engine import (
    default_decision_for_risk,
    max_risk,
    risk_reason,
    rule_matches,
    rule_risk_floor,
)

_DECISION_RANK = {"allow": 0, "confirm": 1, "deny": 2}

# ARGS_TOO_LARGE：内置硬兜底（不可被 policy 替换关掉）。阈值宽松（64KB）。
_ARGS_SIZE_LIMIT = 64 * 1024


@dataclass(frozen=True)
class _Hit:
    """内部命中结果，统一规则命中与路径命中。"""

    decision: str
    risk: RiskLevel
    rule_id: str
    reason: str
    safer_alternative: str | None = None
    approval_role: str | None = None


class RuleBasedPolicyEngine:
    """D 的首版策略引擎。

    构造签名：(policy: PolicySet, registry: ToolRegistry)。
    registry 必须与 gateway 注入的是同一实例，否则注册表漂移导致判执不一致。
    evaluate 无 IO、无随机、无时间依赖、无可变全局状态（确定性铁律）。
    """

    def __init__(
        self, policy: PolicySet = DEFAULT_POLICY, registry: ToolRegistry | None = None
    ) -> None:
        self._policy = policy
        self._registry: ToolRegistry = registry if registry is not None else ToolRegistry()

    def rules(self) -> list[PolicyRule]:
        """返回当前生效的规则列表（commit 3 增量：/api/policy/rules 用）。"""
        return list(self._policy.rules)

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        """对单个候选工具做三态裁决。"""
        # 0. ARGS_TOO_LARGE 内置硬兜底（优先判，不可被规则文件关掉）
        try:
            args_size = len(json.dumps(tool.args, ensure_ascii=False))
        except (TypeError, ValueError):
            args_size = _ARGS_SIZE_LIMIT + 1  # 无法序列化 → 视为超大
        if args_size > _ARGS_SIZE_LIMIT:
            return PolicyVerdict(
                decision="deny",
                final_risk="R4",
                matched_rules=["ARGS_TOO_LARGE"],
                reason=f"args 序列化后超过 {_ARGS_SIZE_LIMIT} 字节，拒绝执行。",
                approval_required=False,
            )

        # 1. 未注册工具保守 deny
        spec = self._registry.get(tool.name)
        if spec is None:
            return PolicyVerdict(
                decision="deny",
                final_risk="R4",
                matched_rules=["UNKNOWN_TOOL"],
                reason=f"unknown tool: {tool.name}",
                safer_alternative="只允许调用已注册 ToolSpec 中的工具。",
                approval_required=False,
            )

        hits: list[_Hit] = []
        hits.extend(_hits_from_rules(self._policy.rules, tool.name, spec.risk, tool.args))
        hits.extend(_hits_from_paths(tool.name, tool.args, self._policy, spec))

        # 兜底：无任何命中 → 按 spec.risk 给默认裁决（DEFAULT_POLICY 的 RISK_* 通常先命中）
        if not hits:
            decision, role, rule_id = default_decision_for_risk(spec.risk)
            hits.append(
                _Hit(
                    decision,
                    spec.risk,
                    rule_id,
                    risk_reason(spec.risk),
                    approval_role=role,
                )
            )

        return _verdict_from_hits(hits, base_risk=spec.risk)


def _hits_from_rules(
    rules: list[PolicyRule], tool_name: str, tool_risk: RiskLevel, args: dict
) -> list[_Hit]:
    hits: list[_Hit] = []
    for rule in rules:
        if not rule_matches(rule, tool_name=tool_name, tool_risk=tool_risk, args=args):
            continue
        hits.append(
            _Hit(
                decision=rule.action,
                risk=_risk_for_rule(rule, tool_risk),
                rule_id=rule.id,
                reason=rule.reason or rule.description or rule.name,
                safer_alternative=rule.safer_alternative,
                approval_role=rule.approval_role,
            )
        )
    return hits


def _risk_for_rule(rule: PolicyRule, tool_risk: RiskLevel) -> RiskLevel:
    """final_risk = max(spec.risk, rule_risk_floor)，用死映射表保证可复算（修正 E）。"""
    floor = rule_risk_floor(rule.action, rule.approval_role)
    return max_risk(tool_risk, floor)


def _hits_from_paths(
    tool_name: str, args: dict, policy: PolicySet, spec: ToolSpec | None = None
) -> list[_Hit]:
    return [
        _hit_from_path(f) for f in classify_paths(tool_name, args, policy.protected_paths, spec)
    ]


def _hit_from_path(finding: PathFinding) -> _Hit:
    return _Hit(
        decision=finding.decision,
        risk=finding.risk,
        rule_id=finding.rule_id,
        reason=finding.reason,
        safer_alternative=finding.safer_alternative,
        approval_role=finding.approval_role,
    )


def _verdict_from_hits(hits: list[_Hit], *, base_risk: RiskLevel) -> PolicyVerdict:
    decision = max((h.decision for h in hits), key=lambda d: _DECISION_RANK[d])
    final_risk = max_risk(base_risk, *(h.risk for h in hits))
    matched_rules = _dedupe([h.rule_id for h in hits])
    primary = _primary_hit(hits, decision)
    return PolicyVerdict(
        decision=cast(Decision, decision),
        final_risk=final_risk,
        matched_rules=matched_rules,
        reason=primary.reason,
        safer_alternative=primary.safer_alternative,
        approval_required=(decision == "confirm"),
        approval_role=primary.approval_role if decision == "confirm" else None,
    )


def _primary_hit(hits: list[_Hit], decision: str) -> _Hit:
    """取最能代表最终裁决的命中：同裁决里按风险最高、出现顺序稳定。"""
    same = [h for h in hits if h.decision == decision]
    return max(same, key=lambda h: {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4}[h.risk])


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


#: L 接线别名：from backend.app.security import PolicyEngine
PolicyEngine = RuleBasedPolicyEngine
