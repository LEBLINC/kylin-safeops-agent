"""阶段2B — cpu/mem 资源工具激活：parser 单元 + overview data_source 升 real。

覆盖：
- parse_free_output：used_percent = (total-available)/total*100（available 权威口径，≈53.2%）；
  无 Mem 行 / 列缺失 → None（缺真）。
- parse_vmstat_output：按 header 定位 id 列（不硬编码列号）、取最后数据行(1s 采样)、usage=100-id；
  **header 列位移用例**（有/无额外列）证明不硬编码；无 id 列/无数据行 → None。
- dispatch：system.cpu_load→CpuLoad、system.mem_usage→MemUsage。
- overview 端到端（罐头执行器）：四项全真 → data_source="real" + cpu/mem 真值；
  缺 cpu 或 mem → partial（诚实降级，绝不假 real）。
- ToolSpec：system.cpu_load/system.mem_usage 已并入 all_specs（R0、无参）。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.app.api._fakes import FakePolicyEngine
from backend.app.api.app import create_app, get_gateway, lifespan
from backend.app.api.routers import system as system_router
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.tool import ToolSpec
from backend.app.contracts.untrusted import ToolResult
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from mcp_servers.os_ops import all_specs
from mcp_servers.os_ops.dispatch import parse_tool_result
from mcp_servers.os_ops.models import CpuLoad, MemUsage
from mcp_servers.os_ops.parsers import parse_free_output, parse_vmstat_output

# free -b 样例：total=10000, available=4680 → used_percent=(10000-4680)/10000=53.2%
_FREE_STDOUT = (
    "               total        used        free      shared  buff/cache   available\n"
    "Mem:           10000        4000         900         100        5000        4680\n"
    "Swap:           2048           0        2048\n"
)

# vmstat 1 2 标准样例：id 列在 header 第 15 位（index 14）；最后数据行 id=95 → usage=5.0
_VMSTAT_STDOUT = (
    "procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----\n"
    " r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st\n"
    " 1  0      0 100000  20000 300000    0    0    10    20  100  200 10  5 80  5  0\n"
    " 0  0      0 100000  20000 300000    0    0     0     0  120  240  3  2 95  0  0\n"
)

# 列位移样例：memory 段多一列（extra）→ id 移到 index 15；硬编码 14 会读错(wa=0)。
# 最后数据行 id=90 → usage=10.0，证明按 header 名定位、不硬编码列号。
_VMSTAT_SHIFTED = (
    "procs ------------memory----------- ---swap-- -----io---- -system-- ------cpu-----\n"
    " r  b   swpd   free   buff  cache  extra   si   so    bi    bo   in   cs us sy id wa st\n"
    " 0  0      0 100000  20000 300000    999    0    0     0     0  120  240  3  2 90  0  0\n"
)


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class _CannedExecutor:
    """注入桩：按工具名返回预置 stdout（确定性，不跑真命令）。"""

    def __init__(self, outputs: dict[str, str]) -> None:
        self._outputs = outputs

    async def execute(self, tool: CandidateTool) -> ToolResult:
        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=0,
            stdout_truncated=self._outputs.get(tool.name, ""),
            is_untrusted=True,
        )


def _probe_gateway(outputs: dict[str, str]) -> MCPGateway:
    """装配 overview 全部无参 R0 探针 registry + allow-all + 罐头执行器。"""
    registry = ToolRegistry()
    for name in (
        "system.info",
        "disk.usage",
        "process.list",
        "system.cpu_load",
        "system.mem_usage",
    ):
        registry.register(
            ToolSpec(
                name=name,
                description=f"探针 {name}",
                risk="R0",
                input_schema={"type": "object", "properties": {}, "additionalProperties": True},
                requires_roles=["operator"],
                reversible=True,
            )
        )
    return MCPGateway(registry, FakePolicyEngine(), _CannedExecutor(outputs))  # type: ignore[arg-type]


# 复用的真值罐头：df 根分区 50%、ps 无僵尸、vmstat usage=5、free used 53.2%
_DF_STDOUT = "Filesystem 1B-blocks Used Available Capacity Mounted on\n/dev/sda1 100 50 50 50% /\n"
_PS_STDOUT = (
    "USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND\n"
    "root 1 0.0 0.1 100 10 ? Ss Dec11 0:01 /sbin/init\n"
)


# ============================================================
# parser 单元
# ============================================================


def test_parse_free_used_percent() -> None:
    mem = parse_free_output(_FREE_STDOUT)
    assert mem is not None
    assert mem.total_bytes == 10000
    assert mem.available_bytes == 4680
    assert mem.used_percent == pytest.approx(53.2, abs=0.05)


def test_parse_free_no_mem_line_none() -> None:
    assert parse_free_output("Swap: 2048 0 2048\n") is None
    assert parse_free_output("garbage") is None


def test_parse_free_missing_available_col_none() -> None:
    """无 available 列（旧版 free，列不足 7）→ None（缺真，不填假值）。"""
    assert parse_free_output("              total  used  free\nMem:  1000  400  600\n") is None


def test_parse_vmstat_takes_last_row_and_locates_id() -> None:
    cpu = parse_vmstat_output(_VMSTAT_STDOUT)
    assert cpu is not None
    assert cpu.usage_percent == pytest.approx(5.0, abs=0.05)  # 100 - 95(最后行 id)


def test_parse_vmstat_header_shift_not_hardcoded() -> None:
    """列位移：id 列因额外列右移，按 header 名定位仍正确（usage=100-90=10）。"""
    cpu = parse_vmstat_output(_VMSTAT_SHIFTED)
    assert cpu is not None
    assert cpu.usage_percent == pytest.approx(10.0, abs=0.05)


def test_parse_vmstat_no_id_or_no_data_none() -> None:
    assert parse_vmstat_output("garbage no header") is None
    # 只有 header 无数据行 → None
    only_header = (
        " r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st\n"
    )
    assert parse_vmstat_output(only_header) is None


def test_dispatch_routes_resource_tools() -> None:
    cpu = parse_tool_result(
        ToolResult(tool="system.cpu_load", args={}, exit_code=0, stdout_truncated=_VMSTAT_STDOUT)
    )
    assert isinstance(cpu, CpuLoad)
    mem = parse_tool_result(
        ToolResult(tool="system.mem_usage", args={}, exit_code=0, stdout_truncated=_FREE_STDOUT)
    )
    assert isinstance(mem, MemUsage)


def test_resource_tools_in_all_specs() -> None:
    names = {s.name for s in all_specs()}
    assert {"system.cpu_load", "system.mem_usage"} <= names
    specs = {s.name: s for s in all_specs()}
    for n in ("system.cpu_load", "system.mem_usage"):
        assert specs[n].risk == "R0"
        # 无参 schema
        assert specs[n].input_schema["properties"] == {}


# ============================================================
# overview 端到端：四项全真 → real / 缺一 → partial
# ============================================================


def test_overview_all_real_data_source_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """四项全真（df/ps/vmstat/free）→ data_source='real' + cpu/mem 真值。"""
    monkeypatch.setattr(system_router, "_overview_cache", None)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = lambda: _probe_gateway(
            {
                "system.info": "host\n",
                "disk.usage": _DF_STDOUT,
                "process.list": _PS_STDOUT,
                "system.cpu_load": _VMSTAT_STDOUT,
                "system.mem_usage": _FREE_STDOUT,
            }
        )
        async with lifespan(app):
            async with _client(app) as client:
                data = (await client.get("/api/system/overview")).json()
                assert data["data_source"] == "real"
                assert data["cpu_usage"] == pytest.approx(5.0, abs=0.05)
                assert data["memory_usage"] == pytest.approx(53.2, abs=0.05)
                assert data["root_disk_usage"] == 50.0
                assert data["zombie_processes"] == 0
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_overview_missing_cpu_stays_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    """cpu 解析失败（vmstat 垃圾）→ cpu 缺真 → data_source 降级 partial（绝不假 real）。"""
    monkeypatch.setattr(system_router, "_overview_cache", None)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = lambda: _probe_gateway(
            {
                "system.info": "host\n",
                "disk.usage": _DF_STDOUT,
                "process.list": _PS_STDOUT,
                "system.cpu_load": "garbage no id column\n",
                "system.mem_usage": _FREE_STDOUT,
            }
        )
        async with lifespan(app):
            async with _client(app) as client:
                data = (await client.get("/api/system/overview")).json()
                assert data["data_source"] == "partial"
                assert data["cpu_usage"] == 0.0  # 缺真不填假值
                assert data["memory_usage"] == pytest.approx(53.2, abs=0.05)
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_overview_missing_mem_stays_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    """mem 解析失败（free 无 Mem 行）→ mem 缺真 → partial。"""
    monkeypatch.setattr(system_router, "_overview_cache", None)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = lambda: _probe_gateway(
            {
                "system.info": "host\n",
                "disk.usage": _DF_STDOUT,
                "process.list": _PS_STDOUT,
                "system.cpu_load": _VMSTAT_STDOUT,
                "system.mem_usage": "no mem line here\n",
            }
        )
        async with lifespan(app):
            async with _client(app) as client:
                data = (await client.get("/api/system/overview")).json()
                assert data["data_source"] == "partial"
                assert data["memory_usage"] == 0.0
                assert data["cpu_usage"] == pytest.approx(5.0, abs=0.05)
        app.dependency_overrides.clear()

    asyncio.run(scenario())
