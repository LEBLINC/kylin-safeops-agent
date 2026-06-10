"""策略集加载器 + 内置默认规则。

设计：
- 规则文件【先用 JSON】（标准库自带，零新依赖；规避 LoongArch wheel 风险）。
  TODO(BLOCKED-ON-L): 是否引入 PyYAML（纯 Python 可用；shield/neurond 形态是 yaml）
  让规则文件改 .yaml？需 L 同意后改 backend/requirements.txt（D 不擅自改）。
- 默认规则 DEFAULT_POLICY 用 Python dict 内嵌，规避部署期"找不到规则文件"问题；
  覆盖 Build-Guide §3.3 列出的核心规则与红队 S001–S007 的关键样本。
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.security.policy_rules import PolicySet

# 默认策略集：覆盖 Build-Guide §3.3 路径保护清单 + 关键规则。
# 规则 id 编号沿用 PI/CMD/FILE/SVC/DBLOG 前缀，便于审计与红队对照（S001–S007）。
DEFAULT_POLICY_DICT: dict = {
    "version": 1,
    "protected_paths": {
        "forbid_modify": ["/", "/boot", "/etc", "/usr", "/bin", "/sbin", "/lib"],
        "forbid_delete": ["/var/lib/mysql", "/var/lib/pgsql"],
        "confirm_required": ["/home"],
        "rotate_only": ["/var/log"],
        "cleanable_limited": ["/tmp"],
    },
    "rules": [
        # ---- 注入/参数级危险模式（来自 Build-Guide §3.3）------------------
        {
            "id": "CMD001",
            "name": "dangerous_rm_root",
            "description": "rm -rf 作用于文件系统根（S001）。",
            "where": "tool_args",
            "match": {"any_arg_matches": [r"rm\s+-rf\s+/(\s|$)"]},
            "action": "deny",
            "severity": "critical",
            "reason": "rm -rf 作用于文件系统根，禁止。",
            "safer_alternative": "限定到具体子目录，并先 dry-run。",
        },
        {
            "id": "CMD002",
            "name": "curl_pipe_shell",
            "description": "curl|sh 远程脚本直执（S004）。",
            "where": "tool_args",
            "match": {"any_arg_matches": [r"(curl|wget).*(\||bash|sh)"]},
            "action": "deny",
            "severity": "critical",
            "reason": "远程脚本直接管入 shell，禁止。",
        },
        {
            "id": "CMD003",
            "name": "chmod_777_system",
            "description": "对系统敏感文件 chmod 777（S003）。",
            "where": "tool_args",
            "match": {
                "any_arg_matches": [r"chmod\s+(0?7{3}|a\+rwx).*/(etc|usr|bin|sbin|lib|boot)"]
            },
            "action": "deny",
            "severity": "critical",
            "reason": "对系统目录开放全权限，禁止。",
        },
        {
            "id": "FILE001",
            "name": "sensitive_shadow_passwd",
            "description": "访问/修改 /etc/shadow 或 /etc/passwd。",
            "where": "tool_args",
            "match": {"any_arg_matches": [r"/etc/(shadow|passwd)(\b|$)"]},
            "action": "deny",
            "severity": "critical",
            "reason": "敏感口令文件，禁止操作。",
        },
        {
            "id": "DBLOG001",
            "name": "db_binlog_delete",
            "description": "误删数据库 binlog（S006）：拒绝直删，要求高级确认/改压缩轮转。",
            "where": "tool_args",
            "match": {"any_arg_matches": [r"/var/lib/mysql/.*bin\.\d+"]},
            "action": "confirm",
            "severity": "high",
            "reason": "数据库 binlog 不可直接删除，需 admin 审批。",
            "safer_alternative": "改用 log.compress_rotate 或通知 DBA 处置。",
            "approval_role": "admin",
        },
        # ---- 输入闸 / 注入语义（应用于 user_input；当前 evaluate 仅看 args，
        #      待 §11.1 与 L 对齐后再启用 user_input 维度，先保留规则定义）---
        {
            "id": "PI001",
            "name": "prompt_injection_ignore_rules",
            "description": "提示词注入：要求忽略/覆盖安全规则（S001/S005）。",
            "where": "tool_args",  # TODO(BLOCKED-ON-L): 切到 user_input 闸后改为 'any'
            "match": {"any_arg_matches": [r"(忽略|忘记|覆盖).*(规则|限制|安全)"]},
            "action": "deny",
            "severity": "high",
            "reason": "检测到提示词注入尝试。",
        },
        # ---- 工具风险等级兜底（与 RiskBasedPolicy 形态对齐；后续 evaluate 接入）-
        {
            "id": "RISK_R4_DENY",
            "name": "r4_always_deny",
            "description": "R4 工具永远 deny（CLAUDE.md §3.5）。",
            "where": "tool_risk",
            "match": {"risk_in": ["R4"]},
            "action": "deny",
            "severity": "critical",
            "reason": "高危破坏性工具禁止使用。",
        },
        {
            "id": "RISK_R3_ADMIN_CONFIRM",
            "name": "r3_admin_confirm",
            "description": "R3 工具需管理员审批（S007 重启服务）。",
            "where": "tool_risk",
            "match": {"risk_in": ["R3"]},
            "action": "confirm",
            "severity": "high",
            "reason": "影响服务的变更需管理员确认。",
            "approval_role": "admin",
        },
        {
            "id": "RISK_R2_OPERATOR_CONFIRM",
            "name": "r2_operator_confirm",
            "description": "R2 可逆变更需运维员审批。",
            "where": "tool_risk",
            "match": {"risk_in": ["R2"]},
            "action": "confirm",
            "severity": "medium",
            "reason": "可逆变更需运维员确认。",
            "approval_role": "operator",
        },
    ],
}

#: 校验通过的默认策略集（模块加载期校验，规则坏掉立即失败）。
DEFAULT_POLICY: PolicySet = PolicySet.model_validate(DEFAULT_POLICY_DICT)


def load_policy_from_dict(data: dict) -> PolicySet:
    """从已解析的 dict 加载并校验策略集。

    Pydantic 校验失败抛 ValidationError，由调用方决定如何处置（启动期失败=不启动）。
    """
    return PolicySet.model_validate(data)


def load_policy_from_json(path: str | Path) -> PolicySet:
    """从 JSON 文件加载策略集。

    路径需调用方保证可信（不来自用户/LLM 输入）；本函数不解析 YAML（TODO 见模块头）。
    """
    text = Path(path).read_text(encoding="utf-8")
    return load_policy_from_dict(json.loads(text))
