"""P1-2: 并发驱动同一 orchestrator 时审计链是否分叉。

先说清楚这个用例要证的东西，因为它和既有 H7-3 长得像但测的不是一回事：

  H7-3 预先算好 200 条链再 gather 提交，测的是 executor 的 FIFO 保序——
  它压根不经过 Orchestrator._append_audit，碰不到共享可变状态。

本用例直接并发调用同一个 Orchestrator 的 _append_audit。该方法在
`await submit_append(...)` 处跨了一个 await，而 self._prev_hash / self._seq
是"await 之前读、await 之后写"的读-改-写：

    curr_hash = compute_curr_hash(self._prev_hash, payload)   # 读
    ...
    await submit_append(self._audit, record)                  # 让出事件循环
    self._prev_hash = curr_hash                               # 写
    self._seq += 1                                            # 写

两个协程若在 await 处交错，就会读到同一份 _prev_hash、领到同一个 seq，
产出两条 seq 相同、prev_hash 相同的记录——哈希链在此分叉，
verify_chain 只能沿一条走，另一条记录事实上从审计上消失了。
对一个安全审计产品来说，这不是"少了条日志"，是审计不可信。

  C-1 并发 append 后，落库记录数 == 提交数（无覆盖丢失）
  C-2 落库记录的 seq 互不重复（不分叉）
  C-3 落库记录首尾相连构成单链（prev_hash 链接完整）
"""

from __future__ import annotations

import asyncio

from backend.app.agent.orchestrator import Orchestrator
from backend.app.audit import write_executor as we
from backend.app.contracts.audit import GENESIS_HASH, AuditRecord
from backend.app.contracts.stream import StreamEvent


class _CollectingSink:
    """记录落库顺序。真 sqlite 落库会经 run_in_executor 跨一次 await；
    此处同步落库即可，交错窗口由 _append_audit 自身的 await 提供。"""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


class _NullEvents:
    def emit(self, event: StreamEvent) -> None:
        pass


def _build() -> tuple[Orchestrator, _CollectingSink]:
    """构造一个只用于直接调 _append_audit 的 orchestrator。

    llm / gateway 传 None：本用例不驱动状态机，只并发打审计，
    这两个依赖在 _append_audit 路径上不参与。
    """
    sink = _CollectingSink()
    orch = Orchestrator(
        llm=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
        audit=sink,
        events=_NullEvents(),
    )
    return orch, sink


async def _drive(orch: Orchestrator, n: int) -> None:
    """并发发起 n 次 _append_audit——这是本用例唯一的施压方式。

    必须装配 executor：未装配时 submit_append 走同步路径、不让出事件循环，
    gather 会退化成顺序执行，缺陷压根不会出现（这正是本用例第一版全绿的原因，
    一个跑绿但什么都没证明的用例）。生产由 lifespan 装配，故装配态才是真实配置。
    """
    we.start_executor()
    try:
        await asyncio.gather(*(orch._append_audit({"i": i}) for i in range(n)))
    finally:
        we.shutdown_executor()


def test_c1_concurrent_append_no_record_loss() -> None:
    """C-1: 并发 append N 条，落库必须是 N 条——少一条就是审计静默丢失。"""
    orch, sink = _build()
    n = 20

    asyncio.run(_drive(orch, n))

    assert len(sink.records) == n, (
        f"C-1: 提交 {n} 条，落库 {len(sink.records)} 条——"
        f"并发下 _append_audit 覆盖了记录（审计静默丢失）"
    )


def test_c2_concurrent_append_seq_unique() -> None:
    """C-2: seq 不得重复——重复即哈希链分叉。"""
    orch, sink = _build()
    n = 20

    asyncio.run(_drive(orch, n))

    seqs = [r.seq for r in sink.records]
    dupes = sorted({s for s in seqs if seqs.count(s) > 1})
    assert not dupes, f"C-2: seq 重复 {dupes}——哈希链分叉，verify_chain 只会沿一条走"


def test_c3_concurrent_append_chain_intact() -> None:
    """C-3: 落库记录必须首尾相连成单链。"""
    orch, sink = _build()
    n = 20

    asyncio.run(_drive(orch, n))

    ordered = sorted(sink.records, key=lambda r: r.seq)
    prev = GENESIS_HASH
    for rec in ordered:
        assert (
            rec.prev_hash == prev
        ), f"C-3: seq={rec.seq} 的 prev_hash 接不上前一条 curr_hash——链断裂"
        prev = rec.curr_hash
