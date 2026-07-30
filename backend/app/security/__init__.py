"""安全护栏：策略引擎、注入检测、风险评分、路径策略。

实现 contracts.policy.PolicyEngine 三态裁决（allow/deny/confirm）。
铁律：evaluate 必须确定性、无副作用——gateway 会调两次（防御纵深），裁决须一致。

本包内子模块：
- policy_rules: 规则数据结构（Pydantic 模型）+ 三态/严重度枚举
- policy_loader: 从 dict / JSON 文件加载规则集，并提供默认规则
- guard: RuleBasedPolicyEngine.evaluate() 三态裁决实现
"""

from backend.app.security.guard import PolicyEngine, RuleBasedPolicyEngine
from backend.app.security.normalize import (
    iter_abspath_values,
    iter_scalar_values,
    normalize_path,
)
from backend.app.security.path_policy import (
    PathFinding,
    canonicalize_linux_path,
    classify_paths,
)
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
)
from backend.app.security.rbac import can_approve

__all__ = [
    # guard
    "PolicyEngine",
    "RuleBasedPolicyEngine",
    # normalize
    "normalize_path",
    "iter_scalar_values",
    "iter_abspath_values",
    # path_policy
    "PathFinding",
    "canonicalize_linux_path",
    "classify_paths",
    # policy_rules
    "Action",
    "PolicyRule",
    "PolicySet",
    "ProtectedPaths",
    "Severity",
    # policy_loader
    "DEFAULT_POLICY",
    "load_policy_from_dict",
    "load_policy_from_json",
    # rbac
    "can_approve",
]
