"""增量5：GET /api/system/overview（Dashboard 概览）。

本轮返回桩/示例数据，让前端 Dashboard 能渲染。
TODO: 接 os_ops 只读工具（system.* / disk.* / process.* / service.*）采集聚合真实指标。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.deps import verify_token
from backend.app.api.schemas import ServiceStatus, SystemOverview

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/overview", response_model=SystemOverview)
async def get_overview(
    _user: str = Depends(verify_token),
) -> SystemOverview:
    """系统概览（桩数据）。

    TODO: 经 MCPGateway 调用 os_ops 只读工具采集 cpu/mem/disk/进程/服务状态后聚合。
    """
    return SystemOverview(
        cpu_usage=12.5,
        memory_usage=43.0,
        root_disk_usage=68.2,
        zombie_processes=0,
        tool_calls_today=0,
        denied_today=0,
        services=[
            ServiceStatus(name="nginx.service", status="running"),
            ServiceStatus(name="sshd.service", status="running"),
        ],
    )
