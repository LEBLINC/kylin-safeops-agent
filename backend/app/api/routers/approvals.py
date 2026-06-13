"""增量3：POST /api/approvals/resume（人工确认闸入口）。

取 SessionRegistry 里同一 Orchestrator 实例，后台调 resume(approved)，事件续推同一 SSE。
挂 Depends(require_proxy_identity)——审批闸授权出自反代签名身份（proxy）/dev 演示态，fail-closed。
trace_id 不存在 / 不在 WAIT_APPROVAL → 4xx 明确报错。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from backend.app.agent.state_machine import State
from backend.app.api.app import get_bus, get_registry
from backend.app.api.auth import Principal
from backend.app.api.deps import require_proxy_identity
from backend.app.api.event_bus import EventBus
from backend.app.api.runner import drive_resume
from backend.app.api.schemas import ResumeRequest, ResumeResponse
from backend.app.api.session_registry import SessionRegistry
from backend.app.security.rbac import can_approve

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


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
