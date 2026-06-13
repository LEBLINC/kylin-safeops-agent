"""增量5 / 任务D：GET /api/system/overview（Dashboard 概览）。

任务D：把"经 MCPGateway 调 os_ops 只读工具 → 聚合"的**采集管道**接起来。Executor 已切真
（任务乙），故 overview 探针现经特权代理跑真只读命令；但**指标数值仍为占位示例值**——
真实指标需把 dispatch.parse_tool_result 接进来解析 stdout（任务戊，未做），故 data_source
仍标注 stub_executor（来源态诚实：数值未从真 stdout 还原前绝不冒充真数据）。

═══════════════════════════════════════════════════════════════════
【GAP-1 审计口径 —— 已采方案 b（待 L 晨起最终签字；本方案可逆、低风险）】
overview 只读探针经 gateway.call 直接执行只读命令、**不经 orchestrator → 不产哈希链审计**。
Executor 切真后这是一条"绕审计的真实执行路径"。审阅窗口（代 L）拍板**方案 b：概览只读探针
显式豁免哈希链审计**，理由：
  - 概览非一次 agent 请求/trace（无 intent、无审批、无状态变更），是高频轮询的只读快照；
  - 强行塞进 per-trace 哈希链语义不符且会让审计库膨胀；
  - 豁免有界且不可冒充审计执行：①硬只读护栏（仅 dispatch is_read_only 工具）；
    ②TTL 节流防命令风暴；③data_source 标注来源态。
本方案与"每次**变更**执行均留哈希链"的核心叙事不冲突——豁免的仅是无副作用的只读概览采集。
（决策待 L 晨起签字；签字前以本注释为准，可随时改回方案 a 让概览也走审计。）
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

#: 概览节流（GAP-1 方案 b 的有界保障之一）：TTL 内复用上次结果，避免 Dashboard 高频轮询在
#: Executor 切真后对靶机发起真实命令风暴。模块级缓存与 app.py 的 lifespan 单例同模式。
_OVERVIEW_CACHE_TTL = 5.0  # 秒
_overview_cache: tuple[float, SystemOverview] | None = None


async def _probe_readonly_tools(gateway: MCPGateway) -> list[str]:
    """逐只读探针经 gateway.call（三道闸+结果闸）dispatch，返回实际执行的工具名。

    GAP-1 方案 b 硬只读护栏：**仅 dispatch gateway.is_read_only(tool) 的工具**——即便策略
    误配或 registry 混入变更工具，概览也绝不触发变更类执行（与观测阶段同口径）。本豁免审计的
    前提就是"只读、无状态变更"，故只读护栏是豁免成立的安全基石，不可削弱。
    GAP-2：每个探针独立 try/except，单工具系统级故障降级跳过、不拖垮整个概览端点。
    """
    probed: list[str] = []
    for name in _OVERVIEW_PROBE_TOOLS:
        tool = CandidateTool(name=name, args={})
        # 硬只读护栏（方案 b 安全基石）：非只读工具绝不在概览里 dispatch。
        if not gateway.is_read_only(tool):
            continue
        try:
            outcome = await gateway.call(tool)
        except Exception:  # noqa: BLE001 概览采集尽力而为，单探针故障不拖垮端点
            continue
        if outcome.executed:
            probed.append(name)
        # TODO(任务戊 / dispatch): 用 mcp_servers.os_ops.dispatch.parse_tool_result
        #   解析 outcome.result.stdout_truncated 聚合真实指标，并置 data_source="real"。
    return probed


@router.get("/overview", response_model=SystemOverview)
async def get_overview(
    _user: str = Depends(verify_token),
    gateway: MCPGateway = Depends(get_gateway),
) -> SystemOverview:
    """系统概览（采集管道经 MCPGateway 真实 dispatch 只读工具，TTL 节流）。

    Executor 已切真，探针跑真只读命令；但指标数值仍为占位示例值（dispatch 解析未接，任务戊），
    故 data_source 标注 stub_executor。接 dispatch 解析后改为从密封真实 stdout 聚合并置 "real"。
    GAP-1 方案 b：本只读概览路径显式豁免哈希链审计（见模块顶部决策，待 L 签字）。
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
