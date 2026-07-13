"""L 域 /api/policy/* 3 接口（commit 3 增量）。

覆盖：rules / events / risk-levels。
认证：require_proxy_identity（决策⑨ mode-aware，proxy fail-closed 401 / dev 放行）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.agent.ports import AuditSink
from backend.app.api import schemas
from backend.app.api.app import get_audit, get_policy
from backend.app.api.auth import Principal
from backend.app.api.deps import require_proxy_identity
from backend.app.contracts.policy import PolicyEngine

router = APIRouter(prefix="/api/policy", tags=["policy"])


def _require_operator_auditor_mode_aware():  # type: ignore[no-untyped-def]
    """L-M4：mode-aware operator/auditor/admin 校验（policy/* 比 audit/* 宽一档）
    - dev 模式：放行（联调期）
    - proxy 模式：roles ∈ {operator, auditor, admin} 才放行，否则 403
    """

    def _dep(
        principal: Principal = Depends(require_proxy_identity),
    ) -> Principal:
        from backend.app.api.deps import _auth_mode

        if _auth_mode() == "proxy" and not ({"operator", "auditor", "admin"} & principal.roles):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"policy/* needs operator/auditor/admin; "
                    f"got roles={sorted(principal.roles)} (fail-closed)"
                ),
            )
        return principal

    return _dep


_operator_dep = _require_operator_auditor_mode_aware()


# 风险等级定义（决策⑬ RBAC fail-closed 同款口径，硬编码字典返）
_RISK_LEVELS: list[dict] = [
    {
        "level": "R0",
        "name": "Read-only",
        "description": "只读探针，无副作用；可自动批准。",
        "auto_approve": True,
        "approval_role_required": None,
        "examples": ["disk.usage", "network.ports", "system.cpu_load", "system.mem_usage"],
    },
    {
        "level": "R1",
        "name": "Read state",
        "description": "读取服务状态，可恢复但仍属状态查询。",
        "auto_approve": True,
        "approval_role_required": None,
        "examples": ["service.status"],
    },
    {
        "level": "R2",
        "name": "Modify (operator)",
        "description": "中等变更：日志压缩、配置查询等。需 operator 审批。",
        "auto_approve": False,
        "approval_role_required": "operator",
        "examples": ["log.compress_rotate"],
    },
    {
        "level": "R3",
        "name": "Privileged (admin)",
        "description": "特权操作：服务重启、删除/修改系统配置。需 admin 审批。",
        "auto_approve": False,
        "approval_role_required": "admin",
        "examples": ["service.restart"],
    },
]


@router.get("/rules", response_model=schemas.PolicyRulesResponse)
async def list_rules(
    engine: PolicyEngine = Depends(get_policy),
    _principal: Principal = Depends(_operator_dep),
) -> schemas.PolicyRulesResponse:
    """列当前生效的策略规则（从 PolicyEngine 派生，含 description / action / severity）。"""
    try:
        rules = engine.rules()
        version = getattr(engine, "_policy", None)
        v = int(getattr(version, "version", 1)) if version is not None else 1
    except AttributeError as exc:
        raise HTTPException(
            status_code=501, detail=f"policy engine does not support rules(): {exc}"
        ) from exc
    return schemas.PolicyRulesResponse(
        rules=[
            schemas.PolicyRuleOut(
                id=r.id,  # type: ignore[attr-defined]
                name=r.name,  # type: ignore[attr-defined]
                description=r.description,  # type: ignore[attr-defined]
                action=r.action,  # type: ignore[attr-defined]
                severity=r.severity,  # type: ignore[attr-defined]
                reason=r.reason,  # type: ignore[attr-defined]
                approval_role=r.approval_role,  # type: ignore[attr-defined]
            )
            for r in rules
        ],
        version=v,
    )


@router.get("/events", response_model=schemas.PolicyEventsResponse)
async def list_events(
    trace_id: str | None = Query(default=None),
    rule_id: str | None = Query(default=None),
    since: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    audit: AuditSink = Depends(get_audit),
    _principal: Principal = Depends(_operator_dep),
) -> schemas.PolicyEventsResponse:
    """列策略事件（从 audit policy_verdict phase 派生）。

    trace_id / rule_id / since 三个可选过滤维度；limit 上限 500。
    """
    try:
        # 直接查 audit_records 全表过滤 phase + 解析 payload
        events = _query_policy_events(
            audit, trace_id=trace_id, rule_id=rule_id, since=since, limit=limit
        )
    except AttributeError as exc:
        raise HTTPException(
            status_code=501, detail=f"audit sink does not support event query: {exc}"
        ) from exc
    return schemas.PolicyEventsResponse(items=events, total=len(events))


@router.get("/risk-levels", response_model=schemas.PolicyRiskLevelsResponse)
async def get_risk_levels(
    _principal: Principal = Depends(_operator_dep),
) -> schemas.PolicyRiskLevelsResponse:
    """返 R0/R1/R2/R3 4 档风险等级定义 + 审批要求 + 样例工具。"""
    return schemas.PolicyRiskLevelsResponse(
        items=[schemas.PolicyRiskLevel(**r) for r in _RISK_LEVELS]
    )


def _query_policy_events(
    audit: AuditSink,
    *,
    trace_id: str | None,
    rule_id: str | None,
    since: str | None,
    limit: int,
) -> list[schemas.PolicyEventOut]:
    """内部：从 audit sink 派生 policy_verdict 事件。

    复用 audit.get_trace_records / list_traces 之外的简单 SQL 直查：单 trace 时直接
    查该 trace 的所有 policy_verdict records；多 trace 时先 list_traces 拿 trace_id
    再逐条 get。
    """
    import json  # noqa: PLC0415

    out: list[schemas.PolicyEventOut] = []
    conn = getattr(audit, "_conn", None)
    if conn is None:
        return out
    if trace_id:
        sql = (
            "SELECT seq, payload, created_at FROM audit_records "
            "WHERE trace_id = ? AND phase = 'policy_verdict'"
        )
        params: list[object] = [trace_id]
        if since:
            sql += " AND created_at >= ?"
            params.append(since)
        sql += " ORDER BY seq ASC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, tuple(params)).fetchall()
    else:
        # 多 trace 模式：先列 trace（按 created_at 倒序），再逐 trace 拉 policy_verdict
        sql = (
            "SELECT trace_id, payload, created_at FROM audit_records "
            "WHERE phase = 'policy_verdict'"
        )
        params = []
        if since:
            sql += " AND created_at >= ?"
            params.append(since)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, tuple(params)).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (json.JSONDecodeError, TypeError):
            continue
        rid = str(payload.get("rule_id", ""))
        if rule_id and rid != rule_id:
            continue
        out.append(
            schemas.PolicyEventOut(
                trace_id=str(row.get("trace_id", trace_id or "")),
                rule_id=rid,
                decision=str(payload.get("decision", "")),
                risk_level=str(payload.get("final_risk", "")),
                user_intent=str(payload.get("user_intent", "")),
                created_at=str(row["created_at"]),
            )
        )
    return out
