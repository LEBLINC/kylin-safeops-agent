"""增量5 / 任务D / 任务戊 / 阶段2B：GET /api/system/overview（Dashboard 概览）。

任务D：把"经 MCPGateway 调 os_ops 只读工具 → 聚合"的**采集管道**接起来（Executor 任务乙已切真，
探针经特权代理跑真只读命令）。
任务戊：把 dispatch.parse_tool_result 接进来，从密封真实 stdout 解析出指标。
阶段2B：cpu/memory 接真源（system.cpu_load=vmstat / system.mem_usage=free），可达 "real"。
各字段来源：
  - root_disk_usage ← disk.usage（df → DiskUsage，取根分区 "/" 的 use_percent）；✅ 真
  - zombie_processes ← process.list（ps → ProcessList，统计 STAT 以 "Z" 开头的进程数）；✅ 真
  - cpu_usage ← system.cpu_load（vmstat 1 秒采样：100-idle，CpuLoad）；✅ 真（阶段2B）
  - memory_usage ← system.mem_usage（free -b：(total-available)/total，MemUsage）；✅ 真（阶段2B）
  - services：service.status 需 service_name、不在无参探针列 → 暂空（不硬塞示例服务，backlog）；
  - tool_calls_today / denied_today：审计计数源未接（backlog）→ 暂置 0。
data_source 据实（诚实红线）：
  - "real"     —— root_disk/zombie/cpu/memory **四项全部从真实 stdout 还原**（阶段2B 起可达）；
  - "partial"  —— 部分字段已从真实 stdout 还原，其余仍缺真实源（如某探针 127/解析失败）；
  - "stub_executor" —— 无任何字段从真实 stdout 还原（探针未执行/未解析出）。
**绝不**出现"填示例值却标 real"——任一字段缺真，data_source 即降级 partial/stub。

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
from backend.app.api.schemas import SystemOverview
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.untrusted import ToolResult
from backend.app.mcp.gateway import MCPGateway
from mcp_servers.os_ops.dispatch import parse_tool_result
from mcp_servers.os_ops.models import CpuLoad, DiskUsage, MemUsage, ProcessList

router = APIRouter(prefix="/api/system", tags=["system"])

#: overview 采集探针：无必填参数的只读工具，经 gateway dispatch 验证管道连通。
#: （system.info/disk.usage/process.list/system.cpu_load/system.mem_usage 均 R0 且 args 可空；
#:   service.status 需 service_name，故不入此列。）
#: 阶段 2B：加 system.cpu_load(vmstat)/system.mem_usage(free) 真源，cpu/memory 转真。
_OVERVIEW_PROBE_TOOLS = (
    "system.info",
    "disk.usage",
    "process.list",
    "system.cpu_load",
    "system.mem_usage",
)

#: 概览节流（GAP-1 方案 b 的有界保障之一）：TTL 内复用上次结果，避免 Dashboard 高频轮询在
#: Executor 切真后对靶机发起真实命令风暴。模块级缓存与 app.py 的 lifespan 单例同模式。
_OVERVIEW_CACHE_TTL = 5.0  # 秒
_overview_cache: tuple[float, SystemOverview] | None = None


async def _probe_readonly_tools(gateway: MCPGateway) -> dict[str, ToolResult]:
    """逐只读探针经 gateway.call（三道闸+结果闸）dispatch，返回 {工具名: 密封 ToolResult}。

    GAP-1 方案 b 硬只读护栏：**仅 dispatch gateway.is_read_only(tool) 的工具**——即便策略
    误配或 registry 混入变更工具，概览也绝不触发变更类执行（与观测阶段同口径）。本豁免审计的
    前提就是"只读、无状态变更"，故只读护栏是豁免成立的安全基石，不可削弱。
    GAP-2：每个探针独立 try/except，单工具系统级故障降级跳过、不拖垮整个概览端点。
    任务戊：返回密封 ToolResult（而非仅工具名），供 get_overview 经 dispatch.parse_tool_result
    解析真实 stdout 聚合指标。
    """
    results: dict[str, ToolResult] = {}
    for name in _OVERVIEW_PROBE_TOOLS:
        tool = CandidateTool(name=name, args={})
        # 硬只读护栏（方案 b 安全基石）：非只读工具绝不在概览里 dispatch。
        if not gateway.is_read_only(tool):
            continue
        try:
            outcome = await gateway.call(tool)
        except Exception:  # noqa: BLE001 概览采集尽力而为，单探针故障不拖垮端点
            continue
        if outcome.executed and outcome.result is not None:
            results[name] = outcome.result
    return results


def _root_disk_usage_percent(disk: DiskUsage | None) -> float | None:
    """从 df 解析结果取根分区 "/" 使用率（百分比）；无解析结果/无根分区 → None。"""
    if disk is None:
        return None
    for fs in disk.filesystems:
        if fs.mount_point == "/":
            return float(fs.use_percent)
    return None


def _zombie_process_count(plist: ProcessList | None) -> int | None:
    """从 ps 解析结果统计僵尸进程数（STAT 以 "Z" 开头，如 Z/Zl/Z+）；无解析结果 → None。"""
    if plist is None:
        return None
    return sum(1 for p in plist.processes if p.stat.startswith("Z"))


@router.get("/overview", response_model=SystemOverview)
async def get_overview(
    _user: str = Depends(verify_token),
    gateway: MCPGateway = Depends(get_gateway),
) -> SystemOverview:
    """系统概览（采集管道经 MCPGateway dispatch 只读工具 + dispatch 解析 + TTL 节流）。

    任务戊/阶段2B：探针密封 stdout 经 parse_tool_result 解析，四项指标据实填真
    （root_disk←df、zombie←ps、cpu←vmstat、memory←free）；data_source 据实置 real/partial/stub。
    四项全真→real；部分真（探针 127/解析失败）→partial；全无→stub。诚实红线：任一缺真不标 real。
    GAP-1 方案 b：本只读概览路径显式豁免哈希链审计（见模块顶部决策）。
    """
    global _overview_cache  # noqa: PLW0603 模块级 TTL 缓存（与 lifespan 单例同模式）
    now = time.monotonic()
    if _overview_cache is not None and now - _overview_cache[0] < _OVERVIEW_CACHE_TTL:
        return _overview_cache[1]

    probe_results = await _probe_readonly_tools(gateway)
    probed = [name for name in _OVERVIEW_PROBE_TOOLS if name in probe_results]

    # dispatch 解析密封 stdout → 结构化模型；解析失败/无解析器返 None，不计入真实字段。
    disk_parsed = (
        parse_tool_result(probe_results["disk.usage"]) if "disk.usage" in probe_results else None
    )
    proc_parsed = (
        parse_tool_result(probe_results["process.list"])
        if "process.list" in probe_results
        else None
    )
    root_disk = _root_disk_usage_percent(
        disk_parsed if isinstance(disk_parsed, DiskUsage) else None
    )
    zombies = _zombie_process_count(proc_parsed if isinstance(proc_parsed, ProcessList) else None)

    # 阶段 2B：cpu/memory 从真实 stdout 解析（vmstat/free）；解析失败/None → 缺真不填假值。
    cpu_parsed = (
        parse_tool_result(probe_results["system.cpu_load"])
        if "system.cpu_load" in probe_results
        else None
    )
    mem_parsed = (
        parse_tool_result(probe_results["system.mem_usage"])
        if "system.mem_usage" in probe_results
        else None
    )
    cpu_usage = cpu_parsed.usage_percent if isinstance(cpu_parsed, CpuLoad) else None
    memory_usage = mem_parsed.used_percent if isinstance(mem_parsed, MemUsage) else None

    # data_source 据实（诚实红线：任一缺真不得标 real）：
    #   real = root_disk/zombie/cpu/memory 四项全部从真实 stdout 还原；
    #   partial = 有真但不全；stub_executor = 全无。
    real_fields = (root_disk, zombies, cpu_usage, memory_usage)
    num_real = sum(1 for f in real_fields if f is not None)
    if num_real == len(real_fields):
        data_source = "real"
    elif num_real > 0:
        data_source = "partial"
    else:
        data_source = "stub_executor"

    overview = SystemOverview(
        cpu_usage=cpu_usage if cpu_usage is not None else 0.0,
        memory_usage=memory_usage if memory_usage is not None else 0.0,
        root_disk_usage=root_disk if root_disk is not None else 0.0,
        zombie_processes=zombies if zombies is not None else 0,
        tool_calls_today=0,  # 审计计数源未接（backlog）
        denied_today=0,  # 审计计数源未接（backlog）
        services=[],  # service.status 需 service_name、不在无参探针列；不硬塞示例服务
        data_source=data_source,
        probed_tools=probed,
    )
    _overview_cache = (now, overview)
    return overview
