"""L 域 X 联调 P1 增量：PolicyRuleOut.safer_alternative 字段补全（commit 1）。

覆盖：
1. T1：seed 规则含 safer_alternative → /api/policy/rules response 含该字段且值正确。
2. T2：规则无 safer_alternative 字段 → response 含 safer_alternative=None（default
   值生效，不报错）。

回归保护：DEFAULT_POLICY 已含 CMD001/CMD002 等规则的 safer_alternative，断言其值
非空字符串；T2 走自定义 PolicySet（不带 safer_alternative）→ 验证 default=None
路径不报错且返回 None。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api.app import create_app, get_audit, get_policy
from backend.app.api.auth import Principal
from backend.app.api.deps import require_proxy_identity
from backend.app.audit import SqliteAuditSink
from backend.app.mcp.registry import ToolRegistry
from backend.app.security import RuleBasedPolicyEngine
from backend.app.security.policy_loader import DEFAULT_POLICY_DICT
from backend.app.security.policy_rules import PolicyRule, PolicySet, ProtectedPaths
from mcp_servers.os_ops import all_specs


def _admin() -> Principal:
    return Principal(user="admin", roles=frozenset({"admin"}))


def _setup(engine=None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_audit] = lambda: SqliteAuditSink(":memory:")
    if engine is not None:
        app.dependency_overrides[get_policy] = lambda: engine
    app.dependency_overrides[require_proxy_identity] = lambda: _admin()
    return TestClient(app)


def _engine_with_default() -> RuleBasedPolicyEngine:
    """复现 D 默认策略引擎：DEFAULT_POLICY_DICT + os_ops 全规格注入。"""
    ps = PolicySet.model_validate(DEFAULT_POLICY_DICT)
    return RuleBasedPolicyEngine(policy=ps, registry=ToolRegistry(all_specs()))


def _engine_without_safer() -> RuleBasedPolicyEngine:
    """构造一份规则集：规则不带 safer_alternative 字段（验证 default=None 路径）。

    注：extra='forbid' 仍要求字段白名单显式声明——所以仍用 model_validate 构造
    PolicyRule，让 safer_alternative 走 default=None。
    """
    rule = PolicyRule.model_validate(
        {
            "id": "PLAIN001",
            "name": "plain_allow",
            "description": "无 safer_alternative 字段的规则（X 联调回归用例）。",
            "match": {"tool_in": ["disk.usage"]},
            "action": "allow",
            "severity": "low",
            "reason": "test default None",
        }
    )
    ps = PolicySet(version=1, rules=[rule], protected_paths=ProtectedPaths())
    return RuleBasedPolicyEngine(policy=ps, registry=ToolRegistry(all_specs()))


# ---- T1：seed 规则含 safer_alternative → response 含该字段且值正确 -----------


def test_policy_rules_includes_safer_alternative() -> None:
    """DEFAULT_POLICY 含 CMD001/CMD002 等带 safer_alternative 的规则。

    验证：GET /api/policy/rules 返回的 rule item 含 safer_alternative 字段，
    且至少一条规则返回非 None 的具体值（CMD001 = "限定到具体子目录，并先 dry-run。"）。
    """
    engine = _engine_with_default()
    with _setup(engine=engine) as client:
        resp = client.get("/api/policy/rules", headers={"X-User-Role": "auditor"})
        assert resp.status_code == 200
        body = resp.json()
        assert "rules" in body
        # 所有 rule item 必须含 safer_alternative 字段（pydantic 默认序列化）
        for r in body["rules"]:
            assert "safer_alternative" in r, f"rule {r.get('id')} 缺 safer_alternative"
        # CMD001 应有非空值
        by_id = {r["id"]: r for r in body["rules"]}
        assert "CMD001" in by_id
        assert by_id["CMD001"]["safer_alternative"] == "限定到具体子目录，并先 dry-run。"
        # DBLOG001 也应有非空值（policy_loader.py:81）
        assert (
            by_id["DBLOG001"]["safer_alternative"] == "改用 log.compress_rotate 或通知 DBA 处置。"
        )


# ---- T2：规则无 safer_alternative → response 含 None default 不报错 ----------


def test_policy_rules_safer_alternative_default_none() -> None:
    """规则对象无 safer_alternative 属性 → response 字段存在且值为 None。

    覆盖：默认值 (default=None) 必须工作；当 policy 引擎 rules() 返回的
    PolicyRule.safer_alternative 为 None 时，PolicyRuleOut 不能抛 AttributeError。
    """
    engine = _engine_without_safer()
    with _setup(engine=engine) as client:
        resp = client.get("/api/policy/rules", headers={"X-User-Role": "auditor"})
        assert resp.status_code == 200
        body = resp.json()
        assert "rules" in body
        assert len(body["rules"]) == 1
        rule = body["rules"][0]
        assert rule["id"] == "PLAIN001"
        # 字段必须存在（pydantic BaseModel 输出 default=None）
        assert "safer_alternative" in rule
        assert rule["safer_alternative"] is None
