"""escalate 审计守门：单写者 + S8 fail-closed 不吞。

历史两层：
  B6 L-M1 移除了 escalate 的 `except: pass`——审计失败不再静默（T5 守它）。
  但那之后 escalate 在生产上**恒 500**：它自己构造 AuditRecord 且 `seq = 0`
  （注释写"audit sink 内部接管 seq 续写"，与实现直接矛盾——audit_logger 明写
  "只落库，绝不重算/覆盖 hash"且 (trace_id, seq) 有 UNIQUE 约束）。
  审批 trace 必然已有记录（orchestrator 自 seq=0 起写到 WAIT_APPROVAL），
  于是 append 必撞 UNIQUE，而 L-M1 让异常真透传 → escalate 永远 500。

  这个缺陷能活下来，是因为原 T5 用 MagicMock 且 last_hash.return_value=""：
  mock 没有 UNIQUE 约束、没有已有链，**结构上观察不到**真实行为。
  故本文件一律用真 SqliteAuditSink + 真 Orchestrator + 已有记录的链
  （E-1/E-2/E-3），只有 S8 透传那条仍需注入故障 sink（E-4）。

  E-1 已有链上 escalate 不 500（钉住"恒不可用"这个缺陷本身）
  E-2 escalate 之后 orchestrator 还能继续写（钉住"别把 500 挪个位置"）
  E-3 单写者不变量：审计链只有一个写者 = 该 trace 的 orchestrator
  E-4 S8 fail-closed：审计落库失败仍透传，不吞（原 T5 的语义，保留）
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from backend.app.agent.orchestrator import Orchestrator
from backend.app.api.auth import Principal
from backend.app.api.routers import approvals as ap
from backend.app.api.schemas import EscalateRequest
from backend.app.api.session_registry import OrchestratorSession, SessionRegistry
from backend.app.audit.audit_logger import SqliteAuditSink


class _Events:
    def __init__(self) -> None:
        self.events: list = []

    def emit(self, event) -> None:  # noqa: ANN001
        self.events.append(event)


def _orchestrator(audit) -> Orchestrator:  # noqa: ANN001
    from backend.app.api._fakes import build_fake_llm, build_gateway

    return Orchestrator(
        llm=build_fake_llm(), gateway=build_gateway(), audit=audit, events=_Events()
    )


async def _seed_chain(orch: Orchestrator, count: int = 2) -> None:
    """把链写到"审批 trace 的真实样子"：已有若干条记录。

    这一步是本文件的关键前提——修前的缺陷只在"链上已有记录"时暴露，
    而 mock 版恰好绕过了它。
    """
    for i in range(count):
        await orch._append_audit({"step": i})


def _registry_with(orch: Orchestrator) -> SessionRegistry:
    registry = SessionRegistry()
    registry._sessions[orch.trace_id] = OrchestratorSession(
        trace_id=orch.trace_id, orchestrator=orch
    )
    return registry


_ADMIN = Principal(user="carol", roles=frozenset({"admin"}))


async def _escalate(orch: Orchestrator) -> object:
    return await ap.escalate_approval(
        trace_id=orch.trace_id,
        body=EscalateRequest(to_user="bob", to_role="operator"),
        principal=_ADMIN,
        registry=_registry_with(orch),
    )


# ---- E-1 / E-2：恒 500 与"别把 500 挪个位置" -------------------------------


def test_e1_escalate_on_existing_chain_does_not_break() -> None:
    """E-1: 链上已有记录时 escalate 必须成功落审计（修前必撞 UNIQUE → 500）。

    断言里刻意不写 `pytest.raises`：修前的表现就是抛 IntegrityError，
    本条要钉的是"它不该抛"。
    """
    audit = SqliteAuditSink(":memory:")
    orch = _orchestrator(audit)

    async def _scenario() -> None:
        await _seed_chain(orch, count=2)
        before = [r["seq"] for r in audit.get_trace_records(orch.trace_id)]
        assert before == [0, 1], f"E-1 前提：链上应已有 seq=[0,1]，实际 {before}"
        resp = await _escalate(orch)
        assert resp.decision == "escalated"  # type: ignore[attr-defined]

    asyncio.run(_scenario())

    records = audit.get_trace_records(orch.trace_id)
    phases = [r["phase"] for r in records]
    assert "approval_escalated" in phases, f"E-1: 转交审计没落库，phases={phases}"
    result = audit.verify_chain(orch.trace_id)
    assert result.valid, f"E-1: 哈希链不可验——{result.reason}"


def test_e2_orchestrator_can_still_write_after_escalate() -> None:
    """E-2: escalate 之后 orchestrator 仍能继续写——防"把 500 挪个位置"。

    这条钉住的是审阅侧最初给的修法（`seq = last_seq + 1`）为什么不够：
    Orchestrator._seq 是纯内存计数（构造置 0、逐次 +1，从不从 DB 重同步），
    端点抢占 seq=N 之后 orchestrator 下一次 _append_audit 仍然领 N → 再撞 UNIQUE。
    而 escalate 不解决审批，该 trace 必然还会被 approve/reject/SoD 继续写，
    所以"escalate 自己不炸"根本不等于修好了。

    实测：seq=last_seq+1 修法下 E-1 绿、本条红。单写者下两条都绿。
    """
    audit = SqliteAuditSink(":memory:")
    orch = _orchestrator(audit)

    async def _scenario() -> None:
        await _seed_chain(orch, count=2)
        await _escalate(orch)
        # 模拟 escalate 之后该 trace 继续被写（approve / SoD 审计都走这条路径）
        await orch._append_audit({"event": "after_escalate"})

    asyncio.run(_scenario())

    seqs = [r["seq"] for r in audit.get_trace_records(orch.trace_id)]
    assert seqs == [0, 1, 2, 3], f"E-2: seq 应连续无冲突，实际 {seqs}"
    result = audit.verify_chain(orch.trace_id)
    assert result.valid, f"E-2: 哈希链不可验——{result.reason}"


# ---- E-3：单写者不变量（防这一类）------------------------------------------


def test_e3_endpoint_does_not_construct_audit_records_itself() -> None:
    """E-3（防这一类）：审批路由不得自己构造 AuditRecord——审计链单写者。

    静态守门，钉的是"一条链两个写者"这个根因，而不是 escalate 这一个端点：
    任何人日后再在本模块里自己算 seq/prev_hash 拼 AuditRecord，当次红。

    单写者比"对齐 seq"更强：它从根上取消竞争，不需要两个写者商量谁用哪个号。
    （G-2 的 RCA 端点是另一种合法形态——它每次新建 trace_id，那条链的
    唯一写者就是它自己，与本条不冲突。本条只约束"往别人的链上写"。）
    """
    from pathlib import Path

    source = Path(ap.__file__).read_text(encoding="utf-8")
    offenders = [
        marker
        for marker in ("AuditRecord(", "compute_curr_hash(", "last_hash(")
        if marker in source
    ]
    assert not offenders, (
        f"E-3: {Path(ap.__file__).name} 自己构造审计记录（{offenders}）——"
        f"该 trace 的链应只由 orchestrator._append_audit 写；"
        f"两个写者各自算 seq 必然撞 (trace_id, seq) UNIQUE"
    )


# ---- E-4：S8 fail-closed（原 T5 的语义）-------------------------------------


def test_e4_audit_failure_still_propagates_not_swallowed() -> None:
    """E-4: 审计落库失败必须透传（S8 fail-closed 不吞）——原 T5 的语义，保留。

    B6 L-M1 移除 `except: pass` 的成果不能因为换写者而丢。
    注入一个 append 恒抛的 sink：异常须一路穿过 orchestrator._append_audit
    → submit_append（await run_in_executor，异常照常透传）→ 端点 → 调用方。
    """

    class _FailingSink:
        def __init__(self) -> None:
            self.calls = 0

        def append(self, record) -> None:  # noqa: ANN001
            self.calls += 1
            raise sqlite3.IntegrityError("audit chain broken")

    sink = _FailingSink()
    orch = _orchestrator(sink)

    with pytest.raises(sqlite3.IntegrityError):
        asyncio.run(_escalate(orch))

    assert sink.calls, "E-4: append 必须真被调（修真前是 except:pass 直接跳过）"
