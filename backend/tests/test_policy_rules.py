"""安全策略：规则结构 + 加载器测试（D 阶段1·增量1）。

只测"规则形态对不对、加载器校验严不严"——不测裁决（裁决在后续增量）。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.app.security import (
    DEFAULT_POLICY,
    PolicyRule,
    PolicySet,
    load_policy_from_dict,
    load_policy_from_json,
)

# ---- DEFAULT_POLICY 自身完整性 -------------------------------------------


def test_default_policy_loads_and_has_critical_rules() -> None:
    """默认规则集模块加载期已通过校验；红队 S001/S004/S006/S007 必须有对应规则。"""
    assert DEFAULT_POLICY.version >= 1
    ids = {r.id for r in DEFAULT_POLICY.rules}
    # S001 rm -rf / / S004 curl|sh / S003 chmod 777 / S006 binlog / S007 restart
    for must in ("CMD001", "CMD002", "CMD003", "DBLOG001", "RISK_R3_ADMIN_CONFIRM"):
        assert must in ids, f"missing critical rule: {must}"


def test_default_policy_protected_paths_cover_baseline() -> None:
    p = DEFAULT_POLICY.protected_paths
    assert "/etc" in p.forbid_modify and "/" in p.forbid_modify
    assert "/var/lib/mysql" in p.forbid_delete
    assert "/var/log" in p.rotate_only


def test_default_policy_rule_ids_unique() -> None:
    ids = [r.id for r in DEFAULT_POLICY.rules]
    assert len(ids) == len(set(ids))


# ---- 加载器：JSON 与 dict --------------------------------------------------


def test_load_from_dict_minimal() -> None:
    data = {
        "version": 1,
        "rules": [
            {
                "id": "X1",
                "name": "n",
                "match": {"tool_in": ["disk.usage"]},
                "action": "allow",
            }
        ],
    }
    ps = load_policy_from_dict(data)
    assert isinstance(ps, PolicySet)
    assert ps.rules[0].action == "allow"


def test_load_from_json_file(tmp_path) -> None:  # noqa: ANN001 pytest fixture
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"version": 1, "rules": []}), encoding="utf-8")
    ps = load_policy_from_json(f)
    assert ps.rules == []


# ---- 校验严格性（违反即抛 ValidationError）-------------------------------


def test_unknown_field_rejected_extra_forbid() -> None:
    """extra='forbid'：杜绝偷渡未声明字段（防 future 字段漂移）。"""
    with pytest.raises(ValidationError):
        load_policy_from_dict(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "x",
                        "name": "n",
                        "match": {},
                        "action": "allow",
                        "ghost_field": "hack",
                    }
                ],
            }
        )


def test_duplicate_rule_id_rejected() -> None:
    with pytest.raises(ValidationError):
        load_policy_from_dict(
            {
                "version": 1,
                "rules": [
                    {"id": "DUP", "name": "a", "match": {}, "action": "allow"},
                    {"id": "DUP", "name": "b", "match": {}, "action": "deny"},
                ],
            }
        )


def test_deny_must_not_have_approval_role() -> None:
    with pytest.raises(ValidationError):
        PolicyRule.model_validate(
            {
                "id": "x",
                "name": "n",
                "match": {},
                "action": "deny",
                "approval_role": "admin",
            }
        )


def test_confirm_requires_approval_role() -> None:
    with pytest.raises(ValidationError):
        PolicyRule.model_validate(
            {"id": "x", "name": "n", "match": {}, "action": "confirm"}
        )


def test_invalid_regex_rejected_at_load() -> None:
    """加载期就要把坏正则筛掉，避免运行时 evaluate 抛异常破坏确定性。"""
    with pytest.raises(ValidationError):
        PolicyRule.model_validate(
            {
                "id": "x",
                "name": "n",
                "match": {"any_arg_matches": ["[unclosed"]},
                "action": "allow",
            }
        )


def test_invalid_risk_level_rejected() -> None:
    """RiskLevel 是 Literal，写错 R5 即拒。"""
    with pytest.raises(ValidationError):
        PolicyRule.model_validate(
            {
                "id": "x",
                "name": "n",
                "match": {"risk_in": ["R5"]},
                "action": "allow",
            }
        )


def test_invalid_action_rejected() -> None:
    """Action 是 Decision Literal：warn/approval 不被接受（语义已合并入 allow/confirm）。"""
    with pytest.raises(ValidationError):
        PolicyRule.model_validate(
            {"id": "x", "name": "n", "match": {}, "action": "warn"}
        )
