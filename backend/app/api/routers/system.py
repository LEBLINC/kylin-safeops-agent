"""增量5 / 任务D：GET /api/system/overview（Dashboard 概览）。

任务D：把"经 MCPGateway 调 os_ops 只读工具 → 聚合"的**采集管道**接起来，使 Executor 一旦
切真（D 的 PR2），overview 自动产出真实指标。

强约束（审计红线）：当前执行器仍是 FakeExecutor，**真数据不可得**——故
① 接的是真实 gateway 调用管道与端点形态，**非真数据**；
② 响应里显式标注 data_source="stub_executor" + probed_tools，**绝不让桩数据冒充真数据**；
③ 数值指标在桩执行器下仍为示例值（无法从桩 stdout 还原），切真 + 接 dispatch 解析后转 real。

═══════════════════════════════════════════════════════════════════
【架构决策待办 GAP-1（审阅复核标记，须在 Executor 切真【前】拍板，勿遗忘）】
overview 探针经 gateway.call 直接执行只读工具，**不经 orchestrator**，因此**不产哈希链审计**
（审计由 orchestrator._append_audit 产出）。这是一条"绕过审计的真实执行路径"：Executor 切真后，
每次 Dashboard 轮询都会跑真命令却无审计痕，与"每次工具执行均留哈希链"的核心叙事冲突。
当前 Executor 为桩 → 暂无害，但属潜伏决策点。二选一（待 L+D 在 集成对齐备忘 §3 拍板）：
  (a) 概览采集也走审计（只读亦留痕）；或
  (b) 明确判定"只读概览探针豁免审计"并写明理由（无状态变更 + 高频 + 已 data_source 标注）。
节流先行（本文件已落地）：TTL 缓存避免高频轮询在靶机引发真实命令风暴。
═══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from backend.app.api.app import get_gateway
from backend.app.api.deps import verify_token
from backend.app.api.schemas import ServiceStatus, SystemOverview
from backend.app.contracts.intent import CandidateTool
from backend.app.mcp.gateway import MCPGateway

router = APIRouter(prefix="/api/system", tags=["system"])

#: overview 采集探针：无必填参数的只读工具，经 gateway dispatch 验证管道连通。
#: （system.info/disk.usage/process.list 均 R0 且 args 可空；
#:   service.status 需 service_name，故不入此列。）
_OVERVIEW_PROBE_TOOLS = ("system.info", "disk.usage", "process.list")

#: 概览节流（GAP-1）：TTL 内复用上次结果，避免 Dashboard 高频轮询在 Executor 切真后
#: 对靶机发起真实命令风暴。模块级缓存与 app.py 的 lifespan 单例同模式。
_OVERVIEW_CACHE_TTL = 5.0  # 秒
_overview_cache: tuple[float, SystemOverview] | None = None


async def _probe_readonly_tools(gateway: MCPGateway) -> list[str]:
    """逐只读探针经 gateway.call（三道闸+结果闸）dispatch，返回实际执行的工具名。

    GAP-2：每个探针独立 try/except，单工具系统级故障降级跳过、不拖垮整个概览端点
    （对齐 orchestrator._collect_observations 的"尽力而为"语义）。
    """
    probed: list[str] = []
    for name in _OVERVIEW_PROBE_TOOLS:
        tool = CandidateTool(name=name, args={})
        # 防御纵深：仅 dispatch 只读工具（与观测阶段同口径，绝不在概览里触发变更）。
        if not gateway.is_read_only(tool):
            continue
        try:
            outcome = await gateway.call(tool)
        except Exception:  # noqa: BLE001 概览采集尽力而为，单探针故障不拖垮端点
            continue
        if outcome.executed:
            probed.append(name)
        # TODO(BLOCKED-ON-D + dispatch): Executor 切真后，用
        #   mcp_servers.os_ops.dispatch.parse_tool_result 解析 outcome.result.stdout_truncated
        #   聚合 cpu/mem/disk/进程/服务真实指标，并把 data_source 置为 "real"。
    return probed


@router.get("/overview", response_model=SystemOverview)
async def get_overview(
    _user: str = Depends(verify_token),
    gateway: MCPGateway = Depends(get_gateway),
) -> SystemOverview:
    """系统概览（采集管道经 MCPGateway 真实 dispatch 只读工具，TTL 节流）。

    桩执行器下采集到的是罐头 stdout，无法还原真实指标——故数值仍为示例值，data_source 标注桩态。
    Executor 切真 + 接 dispatch 解析后，改为从密封真实 stdout 聚合指标并置 data_source="real"。
    """
    global _overview_cache  # noqa: PLW0603 模块级 TTL 缓存（与 lifespan 单例同模式）
    now = time.monotonic()
    if _overview_cache is not None and now - _overview_cache[0] < _OVERVIEW_CACHE_TTL:
        return _overview_cache[1]

    probed = await _probe_readonly_tools(gateway)
    overview = SystemOverview(
        # 桩执行器下为示例值（data_source 已标注）；切真后由 dispatch 的真实结果填充。
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
        data_source="stub_executor",
        probed_tools=probed,
    )
    _overview_cache = (now, overview)
    return overview
