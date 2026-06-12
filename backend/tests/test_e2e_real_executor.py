"""任务 A — Executor 维度 fake→real 集成验证哨兵（端到端，预置待命）。

与 L1 哨兵（test_e2e_real_policy.py）同源的成功模式：在 D 的 PR2 真 Executor 合入前
预置完整集成脚手架，**合入即自动激活**，前置 PR2 集成风险。

当前安全闭环"后半条"（策略放行 → 沙箱内最小权限执行 → 真实兜底）全靠 FakeExecutor 罐头，
零真实覆盖；"即便 LLM 生成 rm -rf / 也无法造成实际损害"目前无法端到端证明。本哨兵在
D 合入后用真 Executor 跑通只读链、真实非零退出、deny 链未触达三条断言，并把 symlink/
TOCTOU 两个占位升级为**编排层真断言**（真 symlink + 真 PrivilegeExecutor realpath 兜底，
win32 跳过、CI ubuntu 真跑；与 D 的执行层用例 test_executor.py 分层互补）。

【精确待命，非裸 except ImportError（L-2 教训）】：
backend.app.executor 当前是"空命名空间包"（仅 .gitkeep，import 成功但无任何 Executor
符号）——故**不能**用 pytest.importorskip("backend.app.executor")（命名空间包导入会成功，
不会 skip）。改为精确检查 D 将导出的真 Executor 符号是否存在：未合入则整文件优雅 skip，
D 的 PR2 导出真 Executor 类/工厂后本哨兵自动激活。若 D 合入后该包 import 抛错（如缺依赖），
import_module 会如实抛出（fail loud），不被静默 skip 掩盖。

【与 D 的接线约定】（仿 L1 的 _make_engine 单点适配）：
- Executor.execute(tool) -> ToolResult（async；方案B：普通失败用 exit_code != 0 承载，
  仅系统级故障 raise）。
- _make_executor() 是唯一构造适配点：D 合入若工厂名/构造签名不同，**只改这一处**。
- _EXECUTOR_SYMBOLS 列出候选导出名；D 实际命名不在其中时，在此追加即可激活。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from unittest.mock import patch

import pytest

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.state_machine import State
from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.stream import StreamEvent
from backend.app.contracts.untrusted import UNTRUSTED_WRAP_TOKEN, ToolResult
from backend.app.llm.adapter import LLMAdapter
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from backend.app.security import DEFAULT_POLICY, PolicyEngine
from mcp_servers.os_ops import all_specs

# ---- 精确待命：定位 D 的真 Executor（PR2 合入即激活）----------------------

#: D 的 PR2 可能导出的真 Executor 工厂/类名（实际命名不在此列时，在此追加即激活）。
#: GAP-3：本列表是"尽量广覆盖"的安全网，但**根治**靠与 D 在 集成对齐备忘 §1/§3 约定一个
#: 冻结导出名（建议 build_executor()），并在 PR2 接线清单加一条"确认本哨兵已转激活（非 skip）"，
#: 避免 D 命名不在列时 PR2 合入后哨兵静默不激活（L-2 静默下线反模式的变体）。
_EXECUTOR_SYMBOLS = (
    "build_executor",
    "create_executor",
    "make_executor",
    "get_executor",
    "Executor",
    "LocalExecutor",
    "PrivilegeExecutor",
    "PrivilegedExecutor",
    "SandboxExecutor",
    "SystemdExecutor",
    "RealExecutor",
    "OsExecutor",
)


def _find_executor_factory() -> object | None:
    """在 backend.app.executor 包内精确查找真 Executor 工厂/类；未合入返回 None。

    import_module 成功但包为空命名空间包（仅 .gitkeep）时无任何候选符号 → None → 整文件
    skip。D 合入真件后命中候选符号 → 返回工厂 → 激活。
    """
    mod = importlib.import_module("backend.app.executor")
    for name in _EXECUTOR_SYMBOLS:
        obj = getattr(mod, name, None)
        if obj is not None:
            return obj
    return None


_EXECUTOR_FACTORY = _find_executor_factory()

if _EXECUTOR_FACTORY is None:
    pytest.skip(
        "待 D 的 PR2 真 Executor 合入（backend.app.executor 暂为空命名空间包，仅 .gitkeep）；"
        "合入并导出真 Executor 后本哨兵自动激活",
        allow_module_level=True,
    )


def _make_executor() -> object:
    """构造 D 的真 Executor（单点适配；D 合入若构造需参数则只改这一处）。"""
    factory = _EXECUTOR_FACTORY
    assert factory is not None  # skip 守卫已保证
    return factory()  # type: ignore[operator]  # 假定无参可构造；如需参数在此适配


# ---- fakes（仅 audit/events/llm；Executor/策略/注册表用真件）---------------


class _RecordingProxy:
    """包裹 D 的真 Executor，记录被调用的工具名（用于断言 deny 链未触达执行）。

    仅做透传 + 记录，不改变执行语义——真命令仍由 D 的 Executor 跑。
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.calls: list[str] = []

    async def execute(self, tool: CandidateTool) -> ToolResult:
        self.calls.append(tool.name)
        return await self._inner.execute(tool)  # type: ignore[attr-defined,no-any-return]


class _Audit:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


class _Events:
    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    def emit(self, event: StreamEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type for e in self.events]


def _llm(intent_obj: dict) -> LLMAdapter:
    payload = json.dumps(intent_obj)

    async def fn(messages):  # noqa: ANN001
        return payload

    return LLMAdapter(completion_fn=fn)


def _build(intent_obj: dict) -> tuple[Orchestrator, _Audit, _Events, _RecordingProxy]:
    registry = ToolRegistry(all_specs())
    executor = _RecordingProxy(_make_executor())
    gateway = MCPGateway(registry, PolicyEngine(DEFAULT_POLICY, registry), executor)  # type: ignore[arg-type]
    audit, events = _Audit(), _Events()
    orch = Orchestrator(
        llm=_llm(intent_obj), gateway=gateway, audit=audit, events=events, trace_id="real-executor"
    )
    return orch, audit, events, executor


def _action_plan(tools: list[dict], *, risk_hint: str = "low") -> dict:
    return {
        "intent": "real_executor_e2e",
        "confidence": 0.9,
        "need_observation": False,
        "candidate_tools": tools,
        "risk_hint": risk_hint,
        "justification": "real executor integration test",
    }


# ---- 适配点：一个"真实会非零退出"的只读场景（D 合入后按真 Executor 行为校准）----
# 约定：只读工具扫描一个不存在的绝对路径 → 命令非零退出（方案B 用 exit_code 承载）。
# 路径非保护路径、绝对、无 ..，策略放行（只读工具不触发 forbid_modify）。
# 若 D 的真命令对不存在路径返回 0，本断言会抓出偏差（这正是哨兵的意义）。
_NONZERO_TOOL = "log.large_log_scan"
_NONZERO_ARGS = {"path": "/nonexistent_kylin_executor_sentinel_zzz"}


# ---- 断言即规格 -----------------------------------------------------------


def test_real_executor_readonly_runs_to_verified_sealed() -> None:
    """断言1：只读 R0 链(disk.usage) → FINISHED，有 verified 事件；tool_result 的 ToolResult
    is_untrusted=True 且 wrap_token 为标准定界符——证明结果闸密封的是**真命令输出**而非罐头。
    """
    orch, _audit, events, ex = _build(_action_plan([{"name": "disk.usage", "args": {}}]))
    end = asyncio.run(orch.run([{"role": "user", "content": "看磁盘"}]))
    assert end is State.FINISHED
    assert ex.calls == ["disk.usage"]  # 真 Executor 被调用
    assert "verified" in events.types()
    tr = [e for e in events.events if e.type == "tool_result"]
    assert tr, "应有 tool_result 事件"
    result = tr[0].data["result"]
    assert result["is_untrusted"] is True
    assert result["wrap_token"] == UNTRUSTED_WRAP_TOKEN


def test_real_executor_nonzero_exit_aggregated_scheme_b() -> None:
    """断言2：真实非零退出场景 → exit_code != 0，状态机按方案B 聚合为 VERIFIED(non_zero)，
    不 raise、不新增失败态（仍走到 FINISHED，verified summary 标记非零）。
    """
    orch, _audit, events, ex = _build(
        _action_plan([{"name": _NONZERO_TOOL, "args": _NONZERO_ARGS}])
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "扫描不存在路径"}]))
    assert end is State.FINISHED  # 方案B：普通失败不 raise、不新增失败态
    assert ex.calls == [_NONZERO_TOOL]
    tr = [e for e in events.events if e.type == "tool_result"]
    assert tr, "应有 tool_result 事件"
    assert tr[0].data["result"]["exit_code"] != 0  # exit_code 真承载失败
    verified = [e for e in events.events if e.type == "verified"][0]
    assert "non-zero" in verified.data["summary"]  # VERIFIED(non_zero) 聚合


def test_real_executor_deny_chain_not_reached() -> None:
    """断言3：deny 链（args 含 /etc/shadow，FILE001）→ REJECTED 且真命令**未执行**
    （可观测：执行代理零调用，无 executing/tool_result 事件）。
    """
    orch, _audit, events, ex = _build(
        _action_plan([{"name": "log.large_log_scan", "args": {"path": "/etc/shadow"}}])
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "扫描"}]))
    assert end is State.REJECTED
    assert ex.calls == []  # 真命令未触达执行
    assert "tool_result" not in events.types()
    assert "executing" not in events.types()


@pytest.mark.skipif(sys.platform == "win32", reason="真 symlink 需 Linux 环境（CI ubuntu 跑）")
def test_real_executor_symlink_escape_guarded(tmp_path) -> None:  # noqa: ANN001
    """编排层真断言：symlink 逃逸被 Executor 的 realpath 兜底拦死（与 D 执行层用例分层互补）。

    场景：tmp_path 下 evil -> /etc/shadow。整链跑真 Orchestrator（真 PolicyEngine +
    真 PrivilegeExecutor）：词法路径（tmp 下的链接）未命中保护，**策略 evaluate 放行**；
    Executor 在 realpath 复核时发现真实目标是 /etc/shadow（FILE001 deny 面），方案B 拒绝。

    从编排层看，这是一次"判定放行、执行兜底"的防御纵深：executed 但 exit≠0（非策略 REJECTED）。
    断言重点 = 真受保护文件从未被读（子进程未起）+ 结果携违规标记 + is_untrusted=True；
    终态 FINISHED（方案B 聚合 non_zero，非崩溃）。
    """
    link = tmp_path / "evil"
    link.symlink_to("/etc/shadow")

    orch, _audit, events, ex = _build(
        _action_plan([{"name": "disk.large_files", "args": {"path": str(link)}}])
    )
    # 真命令绝不能起：受保护文件从未被读（杜绝 TOCTOU 窗口）
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        end = asyncio.run(orch.run([{"role": "user", "content": "扫描可疑链接"}]))

    mock_exec.assert_not_called()  # 子进程从未启动
    assert end is State.FINISHED  # 方案B：执行兜底失败不崩溃、不新增失败态
    assert ex.calls == ["disk.large_files"]  # executor 被调起（在其内部兜底拦截）
    tr = [e for e in events.events if e.type == "tool_result"]
    assert tr, "应有 tool_result 事件（方案B 失败仍产结果）"
    result = tr[0].data["result"]
    assert result["exit_code"] != 0  # 违规 → 非零退出
    stdout = result["stdout_truncated"]
    assert "FILE001" in stdout or "violates protection" in stdout
    assert result["is_untrusted"] is True
    # 编排层是执行兜底失败（FINISHED/non_zero），不是策略 REJECTED
    verified = [e for e in events.events if e.type == "verified"]
    assert verified and "non-zero" in verified[0].data["summary"]


@pytest.mark.skipif(sys.platform == "win32", reason="真 symlink 需 Linux 环境（CI ubuntu 跑）")
def test_real_executor_toctou_not_exploitable(tmp_path) -> None:  # noqa: ANN001
    """编排层真断言：TOCTOU（指向 confirm_required 保护目录的 symlink）不可利用。

    场景：tmp_path 下 evil -> /home（命中 PATH_CONFIRM_REQUIRED）。词法路径策略放行，
    Executor 执行期 realpath 解析回 /home 并被复核拦死——审批针对的是评估时的词法路径，
    不能迁移到策略层从未见过的真实目标。

    断言：子进程从未启动 + 结果携 PATH_CONFIRM_REQUIRED 违规标记 + is_untrusted=True；
    终态 FINISHED（方案B）。
    """
    link = tmp_path / "evil"
    link.symlink_to("/home")

    orch, _audit, events, ex = _build(
        _action_plan([{"name": "disk.large_files", "args": {"path": str(link)}}])
    )
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        end = asyncio.run(orch.run([{"role": "user", "content": "扫描可疑链接"}]))

    mock_exec.assert_not_called()  # 子进程从未启动
    assert end is State.FINISHED
    assert ex.calls == ["disk.large_files"]
    tr = [e for e in events.events if e.type == "tool_result"]
    assert tr, "应有 tool_result 事件"
    result = tr[0].data["result"]
    assert result["exit_code"] != 0
    assert "PATH_CONFIRM_REQUIRED" in result["stdout_truncated"]
    assert result["is_untrusted"] is True
