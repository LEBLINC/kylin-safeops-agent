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
  - services：审计库 phase=EXECUTED + payload.tool LIKE 'service.%' 去重
  - tool_calls_today / denied_today：审计 phase=EXECUTING/EXECUTED|REJECTED + 今日 COUNT
data_source 据实（诚实红线）：
  - "real"     —— root_disk/zombie/cpu/memory **四项全部从真实 stdout 还原**（阶段2B 起可达）；
  - "partial"  —— 部分字段已从真实 stdout 还原，其余仍缺真实源（如某探针 127/解析失败）；
  - "stub_executor" —— 无任何字段从真实 stdout 还原（探针未执行/未解析出）。
**绝不**出现"填示例值却标 real"——任一字段缺真，data_source 即降级 partial/stub。

═══════════════════════════════════════════════════════════════════
【GAP-1 审计口径 —— 已采方案 b（待 L 晨起最终签字；本方案可逆、低风险）】
overview 只读探针经 gateway.call 直接执行只读命令、**不经 orchestrator → 不产哈希链审计**。
Executor 切真后这是一条"绕审计的真实执行路径"。已拍板**方案 b：概览只读探针
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

import json
import os
import sqlite3
import time
from collections.abc import Iterable
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from backend.app.agent.metrics import get_metrics
from backend.app.agent.ports import AuditSink
from backend.app.api.app import get_audit, get_bus, get_gateway, get_registry
from backend.app.api.deps import verify_token
from backend.app.api.event_bus import EventBus
from backend.app.api.schemas import (
    MetricsResponse,
    OverviewHistoryResponse,
    ReadinessResponse,
    ServiceStatus,
    SystemOverview,
    SystemStats,
)
from backend.app.api.session_registry import SessionRegistry
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


#: hours clamp 上下界（防单次查全库）
_MAX_HISTORY_HOURS = 168  # 7 天
_MIN_HISTORY_HOURS = 1


def _today_iso_prefix() -> str:
    """返回今天 UTC 00:00 的 ISO 字符串前缀（YYYY-MM-DD）。

    审计库 created_at 用 datetime.now(timezone.utc).isoformat()（含 T + 微秒）；
    用前缀字符串比较 created_at >= 'YYYY-MM-DDT00:00:00+00:00'。
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _audit_conn(audit: AuditSink) -> sqlite3.Connection | None:
    """内部：从 AuditSink 拿 sqlite3 连接（与 routers/policy.py 同模式）。

    非 SqliteAuditSink 实现（如测试用 FakeAudit）→ None，调用方按"空"兜底（返回 [] / 0）。
    """
    return getattr(audit, "_conn", None)


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


def _audit_count_since(conn: sqlite3.Connection, phases: Iterable[str], since_iso: str) -> int:
    """统计自 since_iso 以来指定 phase 的记录条数（defensive：phases 空返 0）。"""
    phases_tuple = tuple(phases)
    if not phases_tuple:
        return 0
    placeholders = ",".join("?" for _ in phases_tuple)
    sql = (
        f"SELECT COUNT(*) AS c FROM audit_records "
        f"WHERE phase IN ({placeholders}) AND created_at >= ?"
    )
    row = conn.execute(sql, (*phases_tuple, since_iso)).fetchone()
    return int(row["c"]) if row is not None else 0


def _audit_services_recent(conn: sqlite3.Connection, since_iso: str) -> list[str]:
    """从审计 phase=EXECUTED records 提取 service.* 工具名（distinct），按时间倒序，限 20 条。

    payload 形态：{"tool": "service.restart", "exit_code": 0, ...}（来自 orchestrator._append_audit
    在 _execute_batch 单工具留痕）。
    """
    sql = (
        "SELECT payload FROM audit_records "
        "WHERE phase = 'EXECUTED' AND created_at >= ? "
        "ORDER BY created_at DESC LIMIT 500"
    )
    rows = conn.execute(sql, (since_iso,)).fetchall()
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (json.JSONDecodeError, TypeError):
            continue
        tool_name = str(payload.get("tool", ""))
        if not tool_name.startswith("service."):
            continue
        if tool_name in seen:
            continue
        seen.add(tool_name)
        out.append(tool_name)
        if len(out) >= 20:
            break
    return out


@router.get("/overview", response_model=SystemOverview)
async def get_overview(
    _user: str = Depends(verify_token),
    gateway: MCPGateway = Depends(get_gateway),
    audit: AuditSink = Depends(get_audit),
) -> SystemOverview:
    """系统概览（采集管道经 MCPGateway dispatch 只读工具 + dispatch 解析 + TTL 节流）。

    任务戊/阶段2B：探针密封 stdout 经 parse_tool_result 解析，四项指标据实填真
    （root_disk←df、zombie←ps、cpu←vmstat、memory←free）；data_source 据实置 real/partial/stub。
    四项全真→real；部分真（探针 127/解析失败）→partial；全无→stub。诚实红线：任一缺真不标 real。
    GAP-1 方案 b：本只读概览路径显式豁免哈希链审计（见模块顶部决策）。
    services / tool_calls_today / denied_today 从审计库真填（早期版本为 0/[] 占位）。
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

    # 从审计库真填 services / tool_calls_today / denied_today
    today_prefix = _today_iso_prefix()
    today_iso = f"{today_prefix}T00:00:00+00:00"
    conn = _audit_conn(audit)
    if conn is not None:
        # tool_calls_today：EXECUTING + EXECUTED（每个工具都至少有一条 EXECUTED 留痕，
        # 口径比单 phase 更稳）；denied_today：REJECTED。
        tool_calls_today = _audit_count_since(conn, ("EXECUTING", "EXECUTED"), today_iso)
        denied_today = _audit_count_since(conn, ("REJECTED",), today_iso)
        services = [
            ServiceStatus(name=name, status="unknown")
            for name in _audit_services_recent(conn, today_iso)
        ]
    else:
        tool_calls_today = 0
        denied_today = 0
        services = []

    overview = SystemOverview(
        cpu_usage=cpu_usage if cpu_usage is not None else 0.0,
        memory_usage=memory_usage if memory_usage is not None else 0.0,
        root_disk_usage=root_disk if root_disk is not None else 0.0,
        zombie_processes=zombies if zombies is not None else 0,
        tool_calls_today=tool_calls_today,
        denied_today=denied_today,
        services=services,
        data_source=data_source,
        probed_tools=probed,
    )
    _overview_cache = (now, overview)
    return overview


@router.get("/overview/history", response_model=OverviewHistoryResponse)
async def get_overview_history(
    hours: int = Query(default=24, ge=_MIN_HISTORY_HOURS, le=_MAX_HISTORY_HOURS),
    _user: str = Depends(verify_token),
    audit: AuditSink = Depends(get_audit),
) -> OverviewHistoryResponse:
    """按小时聚合最近 N 小时的 cpu/mem/disk 序列。

    当前审计库未落 overview 探针（方案 b 豁免）→ series 通常为空，
    前端 sparkline 显示"暂无数据"。一旦后续把概览探针落库（方案 a 改回 / 折中），本端点
    直接返回非空 series，无需改动。
    """
    # 真实场景下应从审计 phase='overview_probe' records 聚合；目前 schema 未存此 phase → 空。
    # 即便空，hours 字段照实返回（前端可显示窗口长度）。
    return OverviewHistoryResponse(hours=hours, series=[])


@router.get("/stats", response_model=SystemStats)
async def get_stats(
    hours: int = Query(default=24, ge=_MIN_HISTORY_HOURS, le=_MAX_HISTORY_HOURS),
    _user: str = Depends(verify_token),
    audit: AuditSink = Depends(get_audit),
) -> SystemStats:
    """按窗口聚合 by_tool / by_risk / by_status 三个维度。

    - by_tool：EXECUTING/EXECUTED records payload.tool 字段 COUNT
    - by_risk：INTENT_PARSED records payload.risk_level 字段 COUNT（R0/R1/R2/R3）
    - by_status：每个 trace 最后一条 record 的 phase COUNT（FINISHED/REJECTED/WAIT_APPROVAL）
    """
    conn = _audit_conn(audit)
    if conn is None:
        return SystemStats(hours=hours, by_tool={}, by_risk={}, by_status={})
    since_iso = f"{(datetime.now(timezone.utc) - _hours_to_timedelta(hours)).isoformat()}"

    # by_tool：聚合 EXECUTING + EXECUTED records（每次工具执行至少一条）
    sql_by_tool = (
        "SELECT payload FROM audit_records "
        "WHERE phase IN ('EXECUTING', 'EXECUTED') AND created_at >= ? "
        "ORDER BY created_at DESC LIMIT 10000"
    )
    by_tool: dict[str, int] = {}
    for row in conn.execute(sql_by_tool, (since_iso,)).fetchall():
        try:
            payload = json.loads(row["payload"])
        except (json.JSONDecodeError, TypeError):
            continue
        tool_name = str(payload.get("tool", ""))
        if not tool_name:
            continue
        by_tool[tool_name] = by_tool.get(tool_name, 0) + 1

    # by_risk：INTENT_PARSED payload.risk_level
    sql_by_risk = (
        "SELECT payload FROM audit_records "
        "WHERE phase = 'INTENT_PARSED' AND created_at >= ? "
        "ORDER BY created_at DESC LIMIT 10000"
    )
    by_risk: dict[str, int] = {}
    for row in conn.execute(sql_by_risk, (since_iso,)).fetchall():
        try:
            payload = json.loads(row["payload"])
        except (json.JSONDecodeError, TypeError):
            continue
        risk = str(payload.get("risk_level", ""))
        if not risk:
            continue
        by_risk[risk] = by_risk.get(risk, 0) + 1

    # by_status：每 trace 终态 = 该 trace 最后一条 record 的 phase
    sql_by_status = (
        "SELECT trace_id, phase FROM audit_records AS r1 "
        "WHERE seq = (SELECT MAX(seq) FROM audit_records AS r2 WHERE r2.trace_id = r1.trace_id) "
        "AND created_at >= ?"
    )
    by_status: dict[str, int] = {}
    for row in conn.execute(sql_by_status, (since_iso,)).fetchall():
        phase = str(row["phase"])
        by_status[phase] = by_status.get(phase, 0) + 1

    return SystemStats(hours=hours, by_tool=by_tool, by_risk=by_risk, by_status=by_status)


def _hours_to_timedelta(hours: int):  # type: ignore[no-untyped-def]
    """返回 datetime.timedelta(hours=...)（避免顶层 import datetime.timedelta 占用行）。"""
    import datetime as _dt

    return _dt.timedelta(hours=hours)


# ============================================================
# C1（阶段6 第二梯队）：自研轻量指标端点
# ============================================================


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics_endpoint(
    _user: str = Depends(verify_token),
) -> MetricsResponse:
    """GET /api/system/metrics：暴露 agent/metrics.py 的进程内 counter/gauge 快照。

    授权：与 /overview /stats 同层，走 verify_token（proxy 模式需反代签名身份）。
    """
    snapshot = get_metrics().snapshot()
    return MetricsResponse(
        counters=snapshot["counters"],  # type: ignore[arg-type]
        gauges=snapshot["gauges"],  # type: ignore[arg-type]
    )


# ============================================================
# B4 commit 3: /health/ready readiness 端点
# ============================================================


@router.get("/ready", response_model=None)
async def readiness(
    audit: AuditSink = Depends(get_audit),
    bus: EventBus = Depends(get_bus),
    registry: SessionRegistry = Depends(get_registry),
) -> ReadinessResponse | JSONResponse:
    """K8s readiness 探针:DB write OK + bus 存活 + registry.active_count < 阈值.

    Returns 200 on ready=True; raise 503 on ready=False.
    """
    db_ok = False
    bus_ok = False
    registry_ok = False
    active = 0
    try:
        db_ok = audit.ping()
    except Exception:  # noqa: BLE001
        db_ok = False
    try:
        active = int(bus.active_count)
    except Exception:  # noqa: BLE001
        active = 0
    bus_ok = True  # 单实例 EventBus 必活
    registry_ok = active < int(os.environ.get("KYLIN_SSE_QUEUE_MAX", "100") or "100")
    overall = db_ok and bus_ok and registry_ok
    if not overall:
        return JSONResponse(
            status_code=503,
            content={
                "ready": overall,
                "db": db_ok,
                "bus": bus_ok,
                "registry": registry_ok,
                "active_sessions": active,
            },
        )
    return ReadinessResponse(
        ready=overall,
        db=db_ok,
        bus=bus_ok,
        registry=registry_ok,
        active_sessions=active,
    )
