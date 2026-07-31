"""G-2: 独立 RCA 端点按场景模板只读采证 + 必留痕（架构者 2026-07-31 裁定 B + 两条件）。

修前：`POST /api/rca/analyze` 自身不采证，`evidence_chain` 永远只有"用户自己输入的
那一条"——`EvidenceTree.vue` / `HashChainViewer.vue` 与五套场景模板全是死代码。
而端点 docstring 写着"RCA 只产报告，不执行任何工具/命令"，该句前半段其实早已为假：
主链路 orchestrator.py:589 一直在调 `collect_rca_evidence` 真跑只读工具并落审计。

裁定不是"加个默认关的开关"，而是**改红线 + 同时把审计接上**：
能执行但记不下来（真执行零审计），正是这条红线当初要拦的东西；
默认关的开关则会让立项收益（评分项④）一分拿不到，还多出一个
"要不要执行工具"的布尔查询参数这一安全语义面。

  R-1 采证真发生：evidence_count > 1，evidence_chain 含真实工具名（验收一）
  R-2 采证必留痕：审计有 rca_scenario_evidence 记录且 verify_chain valid（验收二）
  R-3 变更类工具被闸拦下，且**实际执行过的工具集合 ⊆ 只读工具集合**（验收三）
  R-4 采证超时仍按已采部分出报告，不 500、不挂死（验收四）
  R-5 遍历全部场景模板，断言每个 evidence_step 的工具都是只读（防这一类）
  R-6 策略误放行时只读闸独自兜住（R-3 抓不到这个，见该用例 docstring）

R-1/R-3/R-4 一律用 Linux 形态输出的 executor 替身（Z-9 模式）：真 executor 在
Windows 上 df/find 跑不起来、在 Linux 上跑得起来，行为依赖平台的断言正是
Z-7 那次 CI 红的成因。registry 与 policy 都用真的——只读闸必须是真闸，
否则这几条断言什么都证明不了。
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routers import rca as rca_module
from backend.app.audit.audit_logger import SqliteAuditSink
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.untrusted import ToolResult
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from backend.app.security import DEFAULT_POLICY, PolicyEngine
from mcp_servers.os_ops import all_specs

#: Linux 上这几个只读工具的真实输出形态（Z-9 模式：本地也能确定性复现真机行为）。
_LINUX_STDOUT = {
    "disk.usage": (
        "Filesystem     1B-blocks        Used   Available Capacity Mounted on\n"
        "/dev/sda1    53687091200 51539607552  2147483648      96% /\n"
    ),
    "disk.large_files": (
        "1288490188\t/var/log/app/access.log\n" "536870912\t/var/log/journal/system.journal\n"
    ),
    "file.lsof_check": (
        "COMMAND   PID USER   FD   TYPE DEVICE     SIZE/OFF NODE NAME\n"
        "nginx    1234 root    5w   REG  253,0    1288490188  42 "
        "/var/log/app/access.log (deleted)\n"
    ),
    "log.large_log_scan": "1288490188\t/var/log/app/access.log\n",
}

#: 五套 RCA 场景。R-5 遍历它做模板侧静态守门。
_ALL_SCENARIOS = (
    "disk_full",
    "zombie_process",
    "io_high",
    "config_drift",
    "service_failure",
)


class _RecordingExecutor:
    """记录**实际执行过**的工具名，并返回 Linux 形态输出。

    刻意记在 executor 而非 gateway.call：executor 是真正跑命令的最后一站，
    "执行过什么"只有这里的记录算数——闸拦下的调用根本到不了这里。
    """

    def __init__(self, *, slow_tools: frozenset[str] = frozenset(), delay_s: float = 1.0) -> None:
        self.executed: list[str] = []
        self._slow_tools = slow_tools
        self._delay_s = delay_s

    async def execute(self, tool: CandidateTool) -> ToolResult:
        self.executed.append(tool.name)
        if tool.name in self._slow_tools:
            await asyncio.sleep(self._delay_s)
        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=0,
            stdout_truncated=_LINUX_STDOUT.get(tool.name, "ok"),
        )


def _real_gated_gateway(executor: _RecordingExecutor) -> MCPGateway:
    """真 registry + 真策略 + 形态替身 executor（与 _fakes.build_gateway 同款装配）。"""
    registry = ToolRegistry(list(all_specs()))
    return MCPGateway(
        registry=registry,
        policy=PolicyEngine(DEFAULT_POLICY, registry),
        executor=executor,  # type: ignore[arg-type]
    )


def _readonly_tool_names() -> set[str]:
    """注册表里所有只读工具名（经 gateway.is_read_only 判定，不硬编码风险等级）。"""
    gateway = _real_gated_gateway(_RecordingExecutor())
    return {
        spec.name for spec in all_specs() if gateway.is_read_only(CandidateTool(name=spec.name))
    }


@pytest.fixture(autouse=True)
def _reset_reports() -> None:
    rca_module._reports.clear()
    yield
    rca_module._reports.clear()


def _client(gateway: MCPGateway, audit: SqliteAuditSink) -> TestClient:
    """装 TestClient 并把 gateway/audit 依赖换成确定性实例。

    用 dependency_overrides 而非起 lifespan：lifespan 会装真 PrivilegeExecutor，
    采证结果就成了平台相关的（Windows 空、Linux 有值），断言随之不可靠。
    """
    from backend.app.api.app import create_app

    app = create_app()
    app.dependency_overrides[rca_module.optional_gateway] = lambda: gateway
    app.dependency_overrides[rca_module.optional_audit] = lambda: audit
    return TestClient(app)


def _analyze(client: TestClient, **overrides: object) -> dict:
    payload = {
        "problem_type": "disk_full",
        "description": "/dev/sda1 96% full, cannot write",
        **overrides,
    }
    resp = client.post("/api/rca/analyze", json=payload)
    assert resp.status_code == 200, f"analyze 未返回 200：{resp.status_code} {resp.text[:300]}"
    return resp.json()


# ---- R-1 / R-2：采证真发生，且真留痕 ----------------------------------------


def test_r1_endpoint_collects_more_than_one_evidence() -> None:
    """R-1（验收一）：不带任何新参数调 analyze → evidence_count > 1 且证据链含真实工具。

    ">1" 是关键：修前恒为"用户输入那一条"，产品在评委面前的表现就是
    RCA 页只有一条证据。这条断言直接钉住立项收益。
    """
    executor = _RecordingExecutor()
    audit = SqliteAuditSink(":memory:")
    body = _analyze(_client(_real_gated_gateway(executor), audit))

    assert body["evidence_count"] > 1, (
        f"R-1: evidence_count={body['evidence_count']}——端点没有采证，"
        f"独立 RCA 页仍然只有用户输入的那一条证据"
    )

    report = rca_module._reports[body["trace_id"]]["report"]
    chain_tools = {str(item.get("source_tool")) for item in report["evidence_chain"]}
    assert chain_tools - {"user.description"}, f"R-1: evidence_chain 只有用户输入：{chain_tools}"
    assert executor.executed, "R-1: 没有任何工具真正执行过"


def test_r2_collection_is_recorded_in_hash_chain() -> None:
    """R-2（验收二）：采证必留痕——审计有 rca_scenario_evidence 记录且链可验。

    这条是本次改红线的前提。原红线之所以能豁免哈希链，立论正是"只读不执行"；
    端点一旦开始跑工具，豁免的基础就没了。没有这条断言，"改红线"就等于
    造出一条真执行、零审计的路径——正是当年 B2 审阅警告过的东西。
    """
    executor = _RecordingExecutor()
    audit = SqliteAuditSink(":memory:")
    body = _analyze(_client(_real_gated_gateway(executor), audit))
    trace_id = body["trace_id"]

    records = audit.get_trace_records(trace_id)
    phases = [r["phase"] for r in records]
    assert "rca_scenario_evidence" in phases, f"R-2: 采证未留痕，phases={phases}"

    recorded = [r for r in records if r["phase"] == "rca_scenario_evidence"][0]
    assert recorded["payload"]["rca_scenario_evidence"] == executor.executed, (
        f"R-2: 审计记录的工具 {recorded['payload']['rca_scenario_evidence']} "
        f"与实际执行的 {executor.executed} 不一致"
    )

    result = audit.verify_chain(trace_id)
    assert result.valid, f"R-2: 哈希链不可验——{result.reason}（broken_seq={result.broken_seq}）"


# ---- R-3：只读闸是真闸（验收三 + 防这一类）----------------------------------


def test_r3_change_class_tool_is_blocked_and_never_executed() -> None:
    """R-3（验收三）：场景模板里混入变更类工具 → 被闸拦下，绝不执行、不进证据。

    为什么必须构造这个输入：今天五套模板恰好全是 R0/R1，只跑现状等于什么都没验——
    "只跑只读"会退化成和原红线一样、没有可执行守卫的一句承诺。

    断言用"**实际执行过的工具集合 ⊆ 只读工具集合**"这个包含关系，遍历真实调用、
    不硬编码工具名：日后谁往任何场景模板里加一个变更工具，当次红。

    **本条钉住的是"复合结果"，不是某一道具体的闸**（变异实测校正，勿误读）：
    真策略下 service.restart(R3) 判 confirm，gateway.call(approved=False) 自己
    就拦掉了；把 is_read_only 整个摘掉本条仍全绿（M-G2-2 = 0 红）。
    单独钉只读闸那道纵深的是 R-6，两条各有分工，别把本条当只读闸的守门。
    """
    executor = _RecordingExecutor()
    gateway = _real_gated_gateway(executor)
    audit = SqliteAuditSink(":memory:")

    poisoned = dict(rca_module._rca_engine.get_scenario_plan("disk_full") or {})
    poisoned["evidence_steps"] = [
        {"tool": "disk.usage", "args": {}},
        # 变更类：R3，schema 合法——故不会因参数不合法被 deny 提前拦掉，
        # 一定是被"审批闸 + 只读闸"这一组纵深拦下的。
        {"tool": "service.restart", "args": {"service_name": "cron.service"}},
    ]
    original = rca_module._rca_engine.get_scenario_plan
    rca_module._rca_engine.get_scenario_plan = lambda _pt: poisoned  # type: ignore[method-assign]
    try:
        body = _analyze(_client(gateway, audit))
    finally:
        rca_module._rca_engine.get_scenario_plan = original  # type: ignore[method-assign]

    assert "service.restart" not in executor.executed, (
        f"R-3: 变更类工具真的被执行了！executed={executor.executed}——"
        f"只读闸没拦住，端点红线形同虚设"
    )

    readonly = _readonly_tool_names()
    assert set(executor.executed) <= readonly, (
        f"R-3: 该端点执行过非只读工具 {set(executor.executed) - readonly}——"
        f"'只跑 R0/R1' 的红线被突破"
    )

    report = rca_module._reports[body["trace_id"]]["report"]
    chain_tools = {str(item.get("source_tool")) for item in report["evidence_chain"]}
    assert "service.restart" not in chain_tools, f"R-3: 变更类工具混进了证据链：{chain_tools}"


def test_r6_read_only_gate_holds_even_if_policy_wrongly_allows() -> None:
    """R-6：策略误放行变更类工具时，只读闸必须**独自**拦住它。

    存在理由（变异实测得来，不是补充设计）：R-3 用真策略跑 service.restart(R3)，
    真策略判 confirm、gateway.call(approved=False) 自己就拦掉了——于是把
    `is_read_only` 整个摘掉，R-3 仍然全绿（M-G2-2 = 0 红）。R-3 验的其实是审批闸。

    而 `is_read_only` 的文档职责原文是"即便策略误放行变更工具，观测阶段也绝不
    执行非只读工具"。要验到这句话，就得让策略真的误放行：这里注入 allow-all 策略，
    此时挡在变更类工具与执行之间的**只剩只读闸**一道。

    注意 is_read_only 读的是 registry 的 spec.risk，不是裁决里的 final_risk——
    所以 allow-all 策略骗不过它，这正是这道闸作为纵深的价值。
    """
    from backend.app.api._fakes import FakePolicyEngine

    executor = _RecordingExecutor()
    registry = ToolRegistry(list(all_specs()))
    gateway = MCPGateway(
        registry=registry,
        policy=FakePolicyEngine(),  # type: ignore[arg-type]
        executor=executor,  # type: ignore[arg-type]
    )
    audit = SqliteAuditSink(":memory:")

    poisoned = dict(rca_module._rca_engine.get_scenario_plan("disk_full") or {})
    poisoned["evidence_steps"] = [
        {"tool": "disk.usage", "args": {}},
        {"tool": "service.restart", "args": {"service_name": "cron.service"}},
    ]
    original = rca_module._rca_engine.get_scenario_plan
    rca_module._rca_engine.get_scenario_plan = lambda _pt: poisoned  # type: ignore[method-assign]
    try:
        _analyze(_client(gateway, audit))
    finally:
        rca_module._rca_engine.get_scenario_plan = original  # type: ignore[method-assign]

    assert "disk.usage" in executor.executed, (
        f"R-6 前提：allow-all 策略下只读工具本应正常执行，executed={executor.executed}——"
        f"前提不成立则本条退化为空转守门"
    )
    assert "service.restart" not in executor.executed, (
        f"R-6: 策略误放行后变更类工具真的被执行了！executed={executor.executed}——"
        f"只读闸这道纵深已失效，RCA 采证可以改系统"
    )


# ---- R-4：超时上界（验收四）-------------------------------------------------


def test_r4_budget_exhausted_still_returns_partial_report() -> None:
    """R-4（验收四）：采证超预算 → 用已采到的部分出报告，不 500、不挂死。

    真机上 find 无 -xdev/-size 约束时单步可达 30s（P2-7）。这里让第一步秒回、
    后续步骤卡住，断言：拿到部分证据、正常 200、整体耗时被预算兜住。

    用界限而不是"默认关的开关"来约束——能力默认可用，代价有上界。
    """
    executor = _RecordingExecutor(
        slow_tools=frozenset({"disk.large_files", "file.lsof_check", "log.large_log_scan"}),
        delay_s=5.0,
    )
    audit = SqliteAuditSink(":memory:")
    client = _client(_real_gated_gateway(executor), audit)

    original_budget = rca_module._EVIDENCE_BUDGET_S
    rca_module._EVIDENCE_BUDGET_S = 0.4
    started = time.monotonic()
    try:
        body = _analyze(client)
    finally:
        rca_module._EVIDENCE_BUDGET_S = original_budget
    elapsed = time.monotonic() - started

    assert body["evidence_count"] >= 1, (
        f"R-4: 超时后连已采到的部分都丢了（evidence_count={body['evidence_count']}）——"
        f"应按已采部分出报告，而不是整轮作废"
    )
    assert elapsed < 4.0, f"R-4: 耗时 {elapsed:.2f}s，预算 0.4s 没有生效——一次 RCA 查询会把请求挂死"
    assert rca_module._reports[body["trace_id"]]["report"], "R-4: 超时路径没产出报告"


# ---- R-5：防这一类（模板侧静态守门）----------------------------------------


def test_r5_every_scenario_step_is_read_only() -> None:
    """R-5（防这一类）：遍历**全部**场景模板，每个 evidence_step 的工具都必须只读。

    R-3 证明闸能拦，本条证明模板本身干净——两条缺一不可：
    只有 R-3 时，模板里混进变更工具也只是被静默跳过，采证能力悄悄少一步没人知道；
    只有 R-5 时，闸坏了也发现不了。

    日后有人给 RCA 加第六个场景、或往现有场景加一个变更工具，当次红。
    """
    gateway = _real_gated_gateway(_RecordingExecutor())
    engine = rca_module._rca_engine

    checked = 0
    offenders: list[tuple[str, str]] = []
    for problem_type in _ALL_SCENARIOS:
        plan = engine.get_scenario_plan(problem_type) or {}
        for step in plan.get("evidence_steps") or []:
            tool_name = str(step.get("tool", ""))
            checked += 1
            if not gateway.is_read_only(CandidateTool(name=tool_name)):
                offenders.append((problem_type, tool_name))

    assert checked > 0, "R-5 前提：一个 evidence_step 都没遍历到——守门空转"
    assert not offenders, (
        f"R-5: 场景模板含非只读工具 {offenders}——RCA 采证会执行变更类工具，"
        f"端点红线被从模板一侧绕过"
    )
