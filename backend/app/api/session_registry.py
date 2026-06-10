"""Orchestrator 实例存活注册表（内存会话管理）。

核心职责：
- 保持 Orchestrator 实例存活直到终态（run 返回 WAIT_APPROVAL 后实例不销毁）。
- resume 时按 trace_id 取出同一实例续跑。
- 终态后标记 done，由定期清理移除（防内存泄漏）。

单实例部署（麒麟靶机单节点），内存 dict 足够；
不做分布式——如需横向扩展，后续可替换为 Redis-backed 实现（不改接口）。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.state_machine import State, is_terminal

# 终态会话保留时间（秒）：前端可能延迟拉取最后几条事件
_RETENTION_SECONDS: float = 300.0


@dataclass
class OrchestratorSession:
    """单次请求的会话上下文。"""

    trace_id: str
    orchestrator: Orchestrator
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    # 当前运行的后台任务引用（防 GC 回收 + 可取消）
    task: asyncio.Task | None = None  # type: ignore[type-arg]

    @property
    def is_done(self) -> bool:
        """会话是否已到终态。"""
        return is_terminal(self.orchestrator.state)

    @property
    def state(self) -> State:
        return self.orchestrator.state


class SessionRegistry:
    """内存会话注册表。

    线程安全由 asyncio 单线程事件循环保证。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, OrchestratorSession] = {}

    def register(self, session: OrchestratorSession) -> None:
        """注册新会话。"""
        self._sessions[session.trace_id] = session

    def get(self, trace_id: str) -> OrchestratorSession | None:
        """按 trace_id 查找会话。"""
        return self._sessions.get(trace_id)

    def mark_done(self, trace_id: str) -> None:
        """标记会话已完成（记录终止时间供清理用）。"""
        session = self._sessions.get(trace_id)
        if session is not None:
            session.finished_at = time.time()

    def cleanup_expired(self) -> list[str]:
        """清理已终止且超过保留时间的会话，返回被清理的 trace_id 列表。

        调用方（app._periodic_cleanup）据此同步移除 EventBus 队列，
        保证 session 与 queue 同生命周期，防 queue 永驻泄漏。
        """
        now = time.time()
        expired = [
            tid
            for tid, s in self._sessions.items()
            if s.finished_at is not None and (now - s.finished_at) > _RETENTION_SECONDS
        ]
        for tid in expired:
            del self._sessions[tid]
        return expired

    @property
    def active_count(self) -> int:
        """当前存活（未到终态）的会话数。"""
        return sum(1 for s in self._sessions.values() if not s.is_done)

    @property
    def total_count(self) -> int:
        """所有会话数（含已完成待清理）。"""
        return len(self._sessions)
