"""增量3：POST /api/approvals/resume（人工确认闸入口）。

取 SessionRegistry 里同一 Orchestrator 实例，后台调 resume(approved)，事件续推同一 SSE。
挂 Depends(require_proxy_identity)——审批闸授权出自反代签名身份（proxy）/dev 演示态，fail-closed。
trace_id 不存在 / 不在 WAIT_APPROVAL → 4xx 明确报错。
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.app.agent.ports import AuditSink
from backend.app.agent.state_machine import State
from backend.app.api import schemas
from backend.app.api.app import get_audit, get_bus, get_registry
from backend.app.api.auth import Principal
from backend.app.api.deps import require_proxy_identity
from backend.app.api.event_bus import EventBus
from backend.app.api.runner import drive_resume
from backend.app.api.schemas import (
    ResumeRequest,
    ResumeResponse,
)
from backend.app.api.session_registry import SessionRegistry
from backend.app.security.rbac import can_approve

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def _admin_bypass_sod(principal: Principal) -> bool:
    """SoD 旁路：admin 角色在运维场景可越级（决策⑬ 撤审需求）。

    普通 user / operator / auditor 一律不许（即便自身已认证）。
    """
    return "admin" in principal.roles


@router.post("/resume", response_model=ResumeResponse)
async def resume_approval(
    body: ResumeRequest,
    principal: Principal = Depends(require_proxy_identity),
    bus: EventBus = Depends(get_bus),
    registry: SessionRegistry = Depends(get_registry),
) -> ResumeResponse:
    """续跑审批：批准→执行整批，拒绝→整批 REJECTED；事件续推同一 SSE。

    认证（require_proxy_identity）已保证调用者身份经验证（proxy 签名 / dev 演示态），非法 → 401。
    授权（RBAC，决策⑬）：
    - **批准**（approved=True）：取本批最严 approval_role，身份多角色取"任一可批即可"
      `any(can_approve(r, required) ...)`；不足 → 403 fail-closed。置于重入锁之前。
    - **拒批**（approved=False）：拒批=取消（安全方向），任何已认证调用者均可，**不校验角色**。
    """
    session = registry.get(body.trace_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown trace_id: {body.trace_id}")
    if session.orchestrator.state is not State.WAIT_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"trace not awaiting approval (state={session.orchestrator.state.value})",
        )

    # 仅**批准**校验角色（拒批=取消，已认证即可）。置于 begin_resume 之前——拒绝时不占用重入锁。
    if body.approved:
        required_role = session.orchestrator.pending_approval_role
        if not any(can_approve(role, required_role) for role in principal.roles):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"roles {sorted(principal.roles)} cannot approve plan requiring "
                    f"'{required_role}' (insufficient/unknown role; fail-closed)"
                ),
            )

        # L-M3 SoD（决策⑬ 强化）：actor == approver 拒批（"自批自"红...资审计）
        try:
            actor = getattr(session.orchestrator, "_actor", None)  # type: ignore[arg-type]
        except Exception:
            actor = None
        if isinstance(actor, dict):
            actor_user = actor.get("user")
            if actor_user and principal.user == actor_user and not _admin_bypass_sod(principal):
                # 写一条 sod_violation 审计（hash 链不变：仅 payload.extra 标记）
                try:
                    # 之六十七 H15: _append_audit 已 async 化，此处必须 await
                    # （否则 coroutine 创建后被 except 吞掉、SoD 违规审计静默丢失）。
                    await session.orchestrator._append_audit(  # type: ignore[attr-defined]
                        payload={
                            "cause": "sod_violation",
                            "actor_user": actor_user,
                            "approver_user": principal.user,
                            "trace_id": body.trace_id,
                        }
                    )
                except Exception:
                    pass  # S8：审计失败不杀安全决策
                raise HTTPException(
                    status_code=403,
                    detail="SoD violation: actor cannot approve own plan",
                )

    # L-4：per-trace 重入保护。状态检查与置位之间无 await（asyncio 单线程原子），
    # 两个 near-simultaneous resume 只有一个能占位，另一个 409，避免双 task 竞态破坏审计/SSE。
    if not registry.begin_resume(body.trace_id):
        raise HTTPException(
            status_code=409, detail=f"resume already in progress for trace {body.trace_id}"
        )

    async def _resume_then_release() -> None:
        try:
            await drive_resume(
                session.orchestrator,
                body.approved,
                bus=bus,
                registry=registry,
                trace_id=body.trace_id,
            )
        finally:
            registry.end_resume(body.trace_id)

    # 后台续跑，runner 兜异常；事件经原 SSEEventSink 进同一 trace_id 队列
    session.task = asyncio.create_task(_resume_then_release())

    return ResumeResponse(trace_id=body.trace_id, accepted=True)


# ---- 列表 / 详情 / 单批审批 / 转交（commit 1 增量）---------------------------


def _to_item(session: object) -> schemas.ApprovalItem:
    """SessionRegistry 内存对象 → ApprovalItem 序列化。

    字段口径：
    - user_intent: 取 orchestrator.user_intent（L 域 run() 入口存的），
      兼容旧实现没存则空串
    - risk_level: 取 orchestrator.state 派生（R0=read-only / R2=confirm_operator /
      R3=confirm_admin），WAIT_APPROVAL 时取 pending_approval_role 反推
    - approval_role: WAIT_APPROVAL 才取 pending_approval_role；其他状态 None
    - created_at: Session.created_at（time.time()）转 ISO 字符串
    """
    orch = getattr(session, "orchestrator", None)
    user_intent = str(getattr(orch, "user_intent", "") or "")
    state = getattr(getattr(orch, "state", None), "value", "UNKNOWN")
    role = None
    if state == "WAIT_APPROVAL":
        try:
            role = orch.pending_approval_role  # type: ignore[attr-defined,union-attr]
        except Exception:
            role = None
    # 之七十二值域修真：兑现本函数 docstring——role→R 级映射（operator=R2/admin=R3/其他=R0）
    # 与 created_at epoch→ISO 转换。此前直接把 "operator"/"admin" 塞进 risk_level、
    # str(time.time()) 塞进 created_at，前端 RiskTag/formatTime 对齐契约后反而渲染异常。
    risk_level = {"operator": "R2", "admin": "R3"}.get(role or "", "R0")
    raw_created = getattr(session, "created_at", None)
    if isinstance(raw_created, int | float):
        created_at = datetime.fromtimestamp(raw_created, tz=timezone.utc).isoformat()
    else:
        created_at = str(raw_created or "")
    return schemas.ApprovalItem(
        trace_id=str(getattr(session, "trace_id", "")),
        user_intent=user_intent,
        risk_level=risk_level,
        approval_role=role,
        state=state,
        created_at=created_at,
    )


@router.get("", response_model=schemas.ApprovalListResponse)
async def list_approvals(
    status: str = "pending",
    registry: SessionRegistry = Depends(get_registry),
    _principal: Principal = Depends(require_proxy_identity),
) -> schemas.ApprovalListResponse:
    """列审批单。status=pending|approved|rejected|all（内存视角，audit 派生视角见 /api/audit/*）。

    当前实现只暴露 SessionRegistry 内存视图；WAIT_APPROVAL=pending，其他=DONE/REJECTED
    归入 status=approved/rejected。S9：绝不返 api_key 类字段。
    """
    wanted = status.lower()
    if wanted not in {"pending", "approved", "rejected", "all"}:
        raise HTTPException(status_code=400, detail=f"invalid status: {status}")

    def _match(item: schemas.ApprovalItem) -> bool:
        if wanted == "all":
            return True
        if wanted == "pending":
            return item.state == "WAIT_APPROVAL"
        if wanted == "approved":
            return item.state == "FINISHED"
        return item.state == "REJECTED"

    items = [_to_item(s) for s in registry.snapshot() if _match(_to_item(s))]
    return schemas.ApprovalListResponse(items=items, total=len(items))


@router.get("/{trace_id}", response_model=schemas.ApprovalItem)
async def get_approval(
    trace_id: str,
    registry: SessionRegistry = Depends(get_registry),
    _principal: Principal = Depends(require_proxy_identity),
) -> schemas.ApprovalItem:
    """单条审批详情。trace 不存在 → 404。"""
    session = registry.get(trace_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown trace_id: {trace_id}")
    return _to_item(session)


async def _resolve_single(
    trace_id: str,
    approved: bool,
    principal: Principal,
    registry: SessionRegistry,
    bus: EventBus,
) -> schemas.ApprovalResolveResponse:
    """单批 approve / reject 复用 resume_approval 路径（决策⑬ RBAC）。"""
    body = ResumeRequest(trace_id=trace_id, approved=approved)
    await resume_approval(body=body, principal=principal, bus=bus, registry=registry)
    return schemas.ApprovalResolveResponse(
        trace_id=trace_id,
        decision="approved" if approved else "rejected",
        by=principal.user,
        accepted=True,
    )


@router.post("/{trace_id}/approve", response_model=schemas.ApprovalResolveResponse)
async def approve_approval(
    trace_id: str,
    principal: Principal = Depends(require_proxy_identity),
    registry: SessionRegistry = Depends(get_registry),
    bus: EventBus = Depends(get_bus),
) -> schemas.ApprovalResolveResponse:
    """单批批准：复用 resume_approval 的 RBAC 校验（决策⑬ 仅 approved=True 过 can_approve）。"""
    return await _resolve_single(trace_id, True, principal, registry, bus)


@router.post("/{trace_id}/reject", response_model=schemas.ApprovalResolveResponse)
async def reject_approval(
    trace_id: str,
    principal: Principal = Depends(require_proxy_identity),
    registry: SessionRegistry = Depends(get_registry),
    bus: EventBus = Depends(get_bus),
) -> schemas.ApprovalResolveResponse:
    """单批拒绝：任何已认证调用者（决策⑬ 拒批=取消，不校验角色）。"""
    return await _resolve_single(trace_id, False, principal, registry, bus)


@router.post("/{trace_id}/escalate", response_model=schemas.ApprovalResolveResponse)
async def escalate_approval(
    trace_id: str,
    body: schemas.EscalateRequest,
    principal: Principal = Depends(require_proxy_identity),
    registry: SessionRegistry = Depends(get_registry),
    audit: AuditSink = Depends(get_audit),
) -> schemas.ApprovalResolveResponse:
    """admin-only 转交：把 trace 重生为新 trace_id + 把 user_intent 复制过去。

    转交审计：emit _append_audit({"event": "approval_escalated", "by": user,
    "from_trace": trace_id, "new_trace": new_id, "to_user": ..., "to_role": ...})。
    """
    if "admin" not in {r.lower() for r in principal.roles}:
        raise HTTPException(
            status_code=403,
            detail=f"escalate requires admin role; got roles={sorted(principal.roles)}",
        )
    src = registry.get(trace_id)
    if src is None:
        raise HTTPException(status_code=404, detail=f"unknown trace_id: {trace_id}")
    new_trace_id = f"{trace_id}-esc-{int.from_bytes(os.urandom(4), 'big'):08x}"
    # 最小实现：emit 一条 escalation audit（orchestrator 自身用 _append_audit 写；
    # 本端点写 audit sink 时按已落库链的 last_hash 续接，符合 S7 字节级 hash 不破）。
    # B6 L-M1 修真：移除 except:pass → 让 audit.append IntegrityError 真 raise (S8 fail-closed 不吞)
    last_hash = audit.last_hash(trace_id) if hasattr(audit, "last_hash") else ""
    from backend.app.contracts.audit import (
        GENESIS_HASH,
        AuditRecord,
        compute_curr_hash,
    )

    payload_dict = {
        "event": "approval_escalated",
        "by": principal.user,
        "from_trace": trace_id,
        "new_trace": new_trace_id,
        "to_user": body.to_user,
        "to_role": body.to_role,
    }
    seq = 0  # audit sink 内部接管 seq 续写 (本端点不重排)
    # compute_curr_hash: prev_hash ∥ canonical_json(payload) → 字节级守门
    # (不动 compute_curr_hash 实现, 仅用)
    curr_hash = compute_curr_hash(prev_hash=last_hash or GENESIS_HASH, payload=payload_dict)
    audit.append(
        AuditRecord(
            trace_id=trace_id,
            seq=seq,
            phase="approval_escalated",
            payload=payload_dict,
            prev_hash=last_hash or GENESIS_HASH,
            curr_hash=curr_hash,
        )
    )
    return schemas.ApprovalResolveResponse(
        trace_id=trace_id,
        decision="escalated",
        by=principal.user,
        new_trace_id=new_trace_id,
        accepted=True,
    )
