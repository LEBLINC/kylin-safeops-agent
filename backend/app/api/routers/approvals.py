"""增量3：POST /api/approvals/resume（人工确认闸入口）。

取 SessionRegistry 里同一 Orchestrator 实例，后台调 resume(approved)，事件续推同一 SSE。
挂 Depends(verify_approval_role)——审批闸入口绝不裸暴露。
trace_id 不存在 / 不在 WAIT_APPROVAL → 4xx 明确报错。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from backend.app.agent.state_machine import State
from backend.app.api.app import get_bus, get_registry
from backend.app.api.deps import verify_approval_role
from backend.app.api.event_bus import EventBus
from backend.app.api.runner import drive_resume
from backend.app.api.schemas import ResumeRequest, ResumeResponse
from backend.app.api.session_registry import SessionRegistry

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.post("/resume", response_model=ResumeResponse)
async def resume_approval(
    body: ResumeRequest,
    _approver: str = Depends(verify_approval_role),
    bus: EventBus = Depends(get_bus),
    registry: SessionRegistry = Depends(get_registry),
) -> ResumeResponse:
    """续跑审批：批准→执行整批，拒绝→整批 REJECTED；事件续推同一 SSE。

    TODO(BLOCKED-ON-D): 接 D 的 RBAC 校验调用者角色 == verdict.approval_role，
    确保"谁能批"由确定性代码强制（当前 verify_approval_role 仅占位放行）。
    """
    session = registry.get(body.trace_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown trace_id: {body.trace_id}")
    if session.orchestrator.state is not State.WAIT_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"trace not awaiting approval (state={session.orchestrator.state.value})",
        )

    # 后台续跑，runner 同样兜异常；事件经原 SSEEventSink 进同一 trace_id 队列
    session.task = asyncio.create_task(
        drive_resume(
            session.orchestrator,
            body.approved,
            bus=bus,
            registry=registry,
            trace_id=body.trace_id,
        )
    )

    return ResumeResponse(trace_id=body.trace_id, accepted=True)
