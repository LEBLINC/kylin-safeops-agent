"""审计落库专用线程池（之七十五 H-7）。

为什么需要它：`SqliteAuditSink.append` 是同步阻塞 IO，且 PRAGMA synchronous=FULL
每条都 fsync。实测真文件落库 p50≈2.0ms / p95≈2.2ms，一次请求 23 条审计即
≈46ms 事件循环阻塞——在这段时间里 SSE 推不出、其它请求排队。

为什么不用 asyncio.to_thread：之六十七 H15 试过并回退。`to_thread` 用的是 loop
的默认 executor，其生命周期绑在 loop 上——`asyncio.run()` 退出时
`_cancel_all_tasks` → loop.close() 不会等默认 executor 里仍在跑的 sqlite 写线程，
线程带着已关闭的 loop/GIL 状态继续跑，在 CI Linux Python 3.11 上触发
`threading._is_owned` C 级 segfault（非 Python 异常，捕不到）。

本模块的解法：进程级 dedicated executor（max_workers=1），生命周期由 app lifespan
显式接管——关闭时 `shutdown(wait=True)` 保证线程排空后才让事件循环退出。
max_workers=1 同时保序（审计链按 seq 落库），与 sink 内部的 _lock 语义一致。

**默认关闭**：未装配 executor 时 `submit_append` 走同步路径，行为与 H-7 之前
逐字节一致。理由：22 个测试文件直接构造 Orchestrator、不走 lifespan，若默认
异步则这些测试又会落进"无人 join 的线程池"这一 H15 原始陷阱。生产由 lifespan
装配后即生效。
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from backend.app.contracts.audit import AuditRecord

logger = logging.getLogger(__name__)


class _Appendable(Protocol):
    def append(self, record: AuditRecord) -> None: ...


#: 进程级审计写线程池；None = 未装配（走同步路径）。由 lifespan 独占管理。
_executor: ThreadPoolExecutor | None = None


def start_executor() -> ThreadPoolExecutor:
    """lifespan 启动时装配。幂等：已装配则原样返回。"""
    global _executor  # noqa: PLW0603
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audit-write")
        logger.info("审计写线程池已启动（max_workers=1，保序）")
    return _executor


def shutdown_executor() -> None:
    """lifespan 关闭时排空线程池。

    `wait=True` 是本方案的命门——它保证所有在途 sqlite 写线程跑完才返回，
    事件循环随后才关闭，从根上消除 H15 的 teardown 竞态。
    """
    global _executor  # noqa: PLW0603
    if _executor is None:
        return
    ex, _executor = _executor, None
    ex.shutdown(wait=True)
    logger.info("审计写线程池已排空关闭")


def get_executor() -> ThreadPoolExecutor | None:
    """当前装配的线程池（None = 未装配，调用方应走同步路径）。"""
    return _executor


async def submit_append(sink: _Appendable, record: AuditRecord) -> None:
    """把一条审计落库交给专用线程池；未装配时同步落库。

    同步回退不是降级容错，而是显式设计：非 lifespan 环境（单测、脚本）下
    没有谁负责 join 线程池，此时同步落库才是安全的。
    """
    ex = _executor
    if ex is None:
        sink.append(record)
        return
    await asyncio.get_running_loop().run_in_executor(ex, sink.append, record)
