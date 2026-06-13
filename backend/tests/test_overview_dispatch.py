"""任务戊 — overview 指标真实解析（dispatch.parse_tool_result）端到端 + 单元验证。

覆盖：
- 抽取纯函数：_root_disk_usage_percent（df→根分区使用率）、_zombie_process_count（ps→STAT=Z 计数）。
- overview 端点：注入"罐头 stdout 执行器"（确定性、不依赖平台真实 df/ps），断言
  root_disk_usage、zombie_processes 从真实 stdout 还原正确、data_source 据实置 partial。
- 只读护栏不变：无探针执行（registry 空）→ data_source 退回 stub_executor。
- 诚实红线：无真实采集时绝不假 real。

注：overview 模块级 TTL 缓存会跨测试驻留——本文件用例均先把 _overview_cache 置 None（与
test_overview_skips_change_tool_defense_in_depth 同手法），避免读到他用例的缓存。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.app.api._fakes import FakePolicyEngine
from backend.app.api.app import create_app, get_gateway, lifespan
from backend.app.api.routers import system as system_router
from backend.app.api.routers.system import _root_disk_usage_percent, _zombie_process_count
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.tool import ToolSpec
from backend.app.contracts.untrusted import ToolResult
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from mcp_servers.os_ops.parsers import parse_df_output, parse_ps_output

# 真实命令样例 stdout（df -PB1 字节单位 / ps aux）。
_DF_STDOUT = (
    "Filesystem 1B-blocks Used Available Capacity Mounted on\n"
    "/dev/sda1 100 68 32 68% /\n"
    "tmpfs 500 0 500 0% /dev/shm\n"
    "/dev/sda2 200 10 190 5% /home\n"
)
_PS_STDOUT = (
    "USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND\n"
    "root         1  0.0  0.1 169436 11892 ?        Ss   Dec11   0:01 /sbin/init\n"
    "root       666  0.0  0.0      0     0 ?        Z    Dec11   0:00 [defunct]\n"
    "alice     7001  1.2  0.5  50000 20000 ?        Zl   Dec11   0:03 [worker]\n"
)


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class _CannedExecutor:
    """注入桩：按工具名返回预置 stdout（确定性，不跑真命令、不依赖平台）。"""

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
    """装配 R0 只读探针 registry + allow-all 策略 + 罐头执行器。"""
    registry = ToolRegistry()
    for name in ("system.info", "disk.usage", "process.list"):
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


# ============================================================
# 抽取纯函数单元
# ============================================================


def test_root_disk_usage_from_df() -> None:
    """df 解析后取根分区 "/" 使用率（68%），非根挂载点不混入。"""
    disk = parse_df_output(_DF_STDOUT)
    assert _root_disk_usage_percent(disk) == 68.0


def test_root_disk_usage_none_when_no_root() -> None:
    """无根分区 / None 输入 → None（不计入真实字段）。"""
    no_root = parse_df_output(
        "Filesystem 1B-blocks Used Available Capacity Mounted on\n/dev/sda2 200 10 190 5% /home\n"
    )
    assert _root_disk_usage_percent(no_root) is None
    assert _root_disk_usage_percent(None) is None


def test_zombie_count_from_ps() -> None:
    """ps 解析后统计 STAT 以 Z 开头的进程（Z + Zl = 2），非僵尸不计。"""
    plist = parse_ps_output(_PS_STDOUT)
    assert _zombie_process_count(plist) == 2


def test_zombie_count_none_input() -> None:
    """None 输入 → None；无僵尸 → 0。"""
    assert _zombie_process_count(None) is None
    healthy = parse_ps_output(
        "USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND\n"
        "root 1 0.0 0.1 100 10 ? Ss Dec11 0:01 /sbin/init\n"
    )
    assert _zombie_process_count(healthy) == 0


# ============================================================
# overview 端点：真实解析 + data_source 据实
# ============================================================


def test_overview_parses_real_metrics_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    """注入罐头 df/ps → root_disk_usage=68、zombie_processes=2；data_source=partial。"""
    monkeypatch.setattr(system_router, "_overview_cache", None)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = lambda: _probe_gateway(
            {"disk.usage": _DF_STDOUT, "process.list": _PS_STDOUT, "system.info": "host\n"}
        )
        async with lifespan(app):
            async with _client(app) as client:
                data = (await client.get("/api/system/overview")).json()
                assert data["root_disk_usage"] == 68.0
                assert data["zombie_processes"] == 2
                # cpu/memory 无真实只读源 → 未采集（0.0），故为 partial 非 real（诚实红线）
                assert data["cpu_usage"] == 0.0
                assert data["memory_usage"] == 0.0
                assert data["data_source"] == "partial"
                # 探针管道连通：三只读探针均执行
                assert set(data["probed_tools"]) == {"system.info", "disk.usage", "process.list"}
                # services 不硬塞示例值
                assert data["services"] == []
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_overview_stub_when_no_probe_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    """无任何只读探针执行（registry 空 → 硬只读护栏全跳过）→ data_source 退回 stub_executor。"""
    monkeypatch.setattr(system_router, "_overview_cache", None)

    async def scenario() -> None:
        app = create_app()
        # 空 registry：探针工具均未注册 → is_read_only=False → 全部跳过、无真实采集。
        app.dependency_overrides[get_gateway] = lambda: MCPGateway(
            ToolRegistry(), FakePolicyEngine(), _CannedExecutor({})
        )  # type: ignore[arg-type]
        async with lifespan(app):
            async with _client(app) as client:
                data = (await client.get("/api/system/overview")).json()
                assert data["probed_tools"] == []
                assert data["data_source"] == "stub_executor"
                assert data["root_disk_usage"] == 0.0
                assert data["zombie_processes"] == 0
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_overview_partial_when_only_disk_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """仅 disk 可解析、ps 为空 → root_disk 真、zombie 退 0；有真字段即 partial。"""
    monkeypatch.setattr(system_router, "_overview_cache", None)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = lambda: _probe_gateway(
            {"disk.usage": _DF_STDOUT, "process.list": "", "system.info": "host\n"}
        )
        async with lifespan(app):
            async with _client(app) as client:
                data = (await client.get("/api/system/overview")).json()
                assert data["root_disk_usage"] == 68.0
                assert data["zombie_processes"] == 0
                assert data["data_source"] == "partial"
        app.dependency_overrides.clear()

    asyncio.run(scenario())
