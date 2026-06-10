"""安全护栏（D）：策略引擎、注入检测、风险评分、路径策略。

实现 contracts.policy.PolicyEngine 三态裁决（allow/deny/confirm）。
铁律：evaluate 必须确定性、无副作用——gateway 会调两次（防御纵深），裁决须一致。

本包内子模块：
- policy_rules: 规则数据结构（Pydantic 模型）+ 三态/严重度枚举
- policy_loader: 从 dict / JSON 文件加载规则集，并提供默认规则
"""

from backend.app.security.policy_loader import (
    DEFAULT_POLICY,
    load_policy_from_dict,
    load_policy_from_json,
)
from backend.app.security.policy_rules import (
    Action,
    PolicyRule,
    PolicySet,
    ProtectedPaths,
    Severity,
    Where,
)

__all__ = [
    "Action",
    "DEFAULT_POLICY",
    "PolicyRule",
    "PolicySet",
    "ProtectedPaths",
    "Severity",
    "Where",
    "load_policy_from_dict",
    "load_policy_from_json",
]
