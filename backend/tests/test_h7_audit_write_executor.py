"""之七十五 H-7: 审计写专用线程池 + graceful shutdown 守门。

背景（务必连着读 backend/app/audit/write_executor.py 的 docstring）：
之六十七 H15 用 asyncio.to_thread 把审计落库挪出主协程，在 CI Linux
Python 3.11 的测试拆解期触发 threading._is_owned **C 级 segfault**——
根因是 to_thread 用 loop 默认 executor，asyncio.run() 退出时不等在途
sqlite 写线程，线程带着已关闭的 loop 状态继续跑。H15 因此回退为同步。

H-7 换成进程级 dedicated executor（max_workers=1），由 lifespan 显式
shutdown(wait=True) 排空。本用例覆盖：

  H7-1 未装配线程池 → 同步落库（22 个直接构造 Orchestrator 的测试走此路径，
       行为与 H-7 之前逐字节一致）
  H7-2 装配后 → 落库确实发生在别的线程（真异步，不是假装）
  H7-3 max_workers=1 保序：并发提交 200 条，落库顺序严格等于提交顺序
       （审计链按 seq 落库，乱序会破坏 verify_chain）
  H7-4 **teardown 回归**：高频 append 后立刻关闭线程池并退出 event loop，
       重复多轮不得崩溃 / 不得丢记录 / verify_chain 仍 valid
       ——这正是 H15 segfault 的复现形状
  H7-5 shutdown 是幂等的，且 shutdown 后回落同步路径（不抛）
  H7-6 shutdown(wait=True) 真的等：慢写入未完成前不返回（不丢审计）
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from backend.app.audit import SqliteAuditSink
from backend.app.audit import write_executor as we
from backend.app.contracts.audit import GENESIS_HASH, AuditRecord, compute_curr_hash


@pytest.fixture(autouse=True)
def _clean_executor():
    """每个用例前后都保证线程池未装配，避免串味。"""
    we.shutdown_executor()
    yield
    we.shutdown_executor()


def _rec(seq: int, prev: str) -> tuple[AuditRecord, str]:
    payload = {"seq": seq}
    curr = compute_curr_hash(prev, payload)
    return (
        AuditRecord(
            trace_id="h7",
            seq=seq,
            phase="EXECUTING",
            payload=payload,
            prev_hash=prev,
            curr_hash=curr,
        ),
        curr,
    )


class _ThreadRecordingSink:
    """记录每条 append 落在哪个线程 + 落库顺序。"""

    def __init__(self) -> None:
        self.threads: list[str] = []
        self.order: list[int] = []

    def append(self, record: AuditRecord) -> None:
        self.threads.append(threading.current_thread().name)
        self.order.append(record.seq)


def test_h7_1_no_executor_falls_back_to_sync() -> None:
    """H7-1: 未装配线程池 → 同步落库（在调用者线程内完成）。"""
    sink = _ThreadRecordingSink()
    rec, _ = _rec(0, GENESIS_HASH)

    async def _drive() -> None:
        assert we.get_executor() is None
        await we.submit_append(sink, rec)

    asyncio.run(_drive())
    assert sink.order == [0]
    assert sink.threads == [threading.main_thread().name], "H7-1: 未装配时应在主线程同步落库"


def test_h7_2_executor_offloads_to_worker_thread() -> None:
    """H7-2: 装配后落库发生在 audit-write 线程，主协程不被阻塞占用。"""
    sink = _ThreadRecordingSink()
    rec, _ = _rec(0, GENESIS_HASH)

    async def _drive() -> None:
        we.start_executor()
        await we.submit_append(sink, rec)

    asyncio.run(_drive())
    assert sink.order == [0]
    assert sink.threads[0].startswith("audit-write"), f"H7-2: 应在专用线程，实际 {sink.threads}"
    assert sink.threads[0] != threading.main_thread().name


def test_h7_3_single_worker_preserves_order() -> None:
    """H7-3: max_workers=1 保序——200 条并发提交的落库顺序 == 提交顺序。

    审计链按 seq 落库；若线程池并发 >1，落库乱序会让 (trace_id, seq) 的
    写入顺序与哈希链顺序脱节。
    """
    sink = _ThreadRecordingSink()
    prev = GENESIS_HASH
    recs = []
    for i in range(200):
        r, prev = _rec(i, prev)
        recs.append(r)

    async def _drive() -> None:
        we.start_executor()
        await asyncio.gather(*(we.submit_append(sink, r) for r in recs))

    asyncio.run(_drive())
    assert sink.order == list(range(200)), "H7-3: 落库顺序必须严格等于提交顺序"
    assert set(sink.threads) == {sink.threads[0]}, "H7-3: 只应有一个写线程"


def test_h7_4_teardown_regression_no_crash_no_loss(tmp_path) -> None:
    """H7-4: H15 segfault 复现形状——高频 append 后立即关闭并退出 loop，多轮。

    每轮：起线程池 → 猛写 60 条真文件审计 → shutdown(wait=True) → loop 退出。
    若 shutdown 没真等线程，这里就是 H15 那个 C 级崩溃的现场。
    断言不止"没崩"，还要求记录零丢失 + 哈希链 valid（崩溃前的静默丢数据同样是缺陷）。
    """
    for round_no in range(5):
        db = tmp_path / f"audit-{round_no}.db"
        sink = SqliteAuditSink(str(db))

        async def _drive(s: SqliteAuditSink = sink) -> None:
            we.start_executor()
            prev = GENESIS_HASH
            for i in range(60):
                rec, prev = _rec(i, prev)
                await we.submit_append(s, rec)

        asyncio.run(_drive())
        # 关键：loop 已退出后才排空——模拟 lifespan 之外的最坏顺序
        we.shutdown_executor()

        rows = sink._conn.execute(
            "SELECT COUNT(*) AS n FROM audit_records WHERE trace_id='h7'"
        ).fetchone()
        assert rows["n"] == 60, f"H7-4 第 {round_no} 轮丢记录：只落库 {rows['n']}/60"
        assert sink.verify_chain("h7").valid, f"H7-4 第 {round_no} 轮哈希链失效"
        sink.close()


def test_h7_5_shutdown_idempotent_and_falls_back_after() -> None:
    """H7-5: shutdown 可重复调用；shutdown 后 submit 回落同步路径（不抛）。"""
    we.start_executor()
    we.shutdown_executor()
    we.shutdown_executor()  # 第二次不得抛
    assert we.get_executor() is None

    sink = _ThreadRecordingSink()
    rec, _ = _rec(0, GENESIS_HASH)

    async def _drive() -> None:
        await we.submit_append(sink, rec)

    asyncio.run(_drive())
    assert sink.order == [0], "H7-5: shutdown 后应回落同步落库，不得丢记录"


def test_h7_6_shutdown_waits_for_inflight_write() -> None:
    """H7-6: shutdown(wait=True) 必须等在途慢写入跑完，不得丢审计。

    构造一个 append 耗时 300ms 的 sink，不 await 直接 shutdown——
    若 shutdown 不等，done 标志就还是 False。
    """
    done = threading.Event()

    class _SlowSink:
        def append(self, record: AuditRecord) -> None:
            time.sleep(0.3)
            done.set()

    sink = _SlowSink()
    rec, _ = _rec(0, GENESIS_HASH)
    ex = we.start_executor()
    ex.submit(sink.append, rec)  # 绕过 await，制造"在途写入"

    we.shutdown_executor()
    assert done.is_set(), "H7-6: shutdown(wait=True) 未等在途写入完成（会丢审计）"


def test_h7_7_lifespan_starts_and_reclaims_executor(monkeypatch, tmp_path) -> None:
    """H7-7: lifespan 装配线程池，退出时可靠回收（不泄漏给后续测试）。

    泄漏是真实风险：22 个测试文件直接构造 Orchestrator 且不走 lifespan，
    若某个 lifespan 测试把线程池留在原地，这些测试就会落进"无人 join 的
    线程池"——正是 H15 segfault 的原始陷阱。
    """
    from fastapi.testclient import TestClient

    monkeypatch.setenv("KYLIN_AUTH_MODE", "dev")
    monkeypatch.setenv("KYLIN_LLM_FAKE", "true")
    monkeypatch.setenv("KYLIN_AUDIT_DB", str(tmp_path / "h7-lifespan.db"))

    from backend.app.api.app import create_app

    assert we.get_executor() is None, "H7-7 前置：进入 lifespan 前不应已装配"
    with TestClient(create_app()):
        assert we.get_executor() is not None, "H7-7: lifespan 内应已装配线程池"
    assert we.get_executor() is None, "H7-7: lifespan 退出后必须回收（否则泄漏给后续测试）"


def test_h7_8_executor_drains_before_audit_close() -> None:
    """H7-8: 关闭顺序——线程池排空必须早于 audit close（源码级守门）。

    顺序颠倒的后果不是崩溃而是静默丢审计：先 close 连接，则线程池里在途的
    append 撞上已关闭的 sqlite 连接。这类顺序不变量无法用行为断言可靠覆盖
    （竞态窗口极窄），故在源码层钉死相对位置。
    """
    import inspect

    from backend.app.api import app as app_mod

    src = inspect.getsource(app_mod.lifespan)
    drain_pos = src.find("shutdown_audit_executor()")
    close_pos = src.find("_audit.close()")
    assert drain_pos != -1, "H7-8: lifespan 未调 shutdown_audit_executor()"
    assert close_pos != -1, "H7-8: lifespan 未调 _audit.close()"
    assert drain_pos < close_pos, "H7-8: 线程池排空必须在 audit close 之前（否则在途写入丢失）"
