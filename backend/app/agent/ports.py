"""Orchestrator 的依赖注入端口（运行时接口，非数据契约）。

这些是 orchestrator 与其协作者之间的**行为接口**，与 contracts/ 的数据模型分层：
- PolicyEngine 已在 contracts/policy.py（D 实现），此处再导出方便集中引用。
- Executor 定义在 mcp 层（gateway 的直接依赖），此处再导出，保持单一引用点
  并避免 agent→mcp→agent 循环导入。
- AuditSink 由 D 实现（backend/app/audit）；此处仅给 Protocol，依赖注入空跑。
- EventSink 由 orchestrator/API 层提供（推流给前端 X）。

放在 agent/ 而非 contracts/：这些是运行时协作接口，非冻结的数据事实来源，
改动不触发契约冻结纪律。若 D 需要不同签名，先对齐再调整（不擅自改）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.policy import PolicyEngine
from backend.app.contracts.stream import StreamEvent
from backend.app.mcp.gateway import Executor

__all__ = ["PolicyEngine", "Executor", "AuditSink", "EventSink"]


@runtime_checkable
class AuditSink(Protocol):
    """审计落库接口（D 的 audit_logger 实现）。

    orchestrator 在每个状态转移点产 AuditRecord 并 append；落库与哈希链校验归 D。

    历史查询扩展（commit 2 增量）：list_traces / get_trace_records / count_traces /
    verify_chain 由 SqliteAuditSink 实现（具体返回 schema 在 routers/audit.py 处理）。
    """

    def append(self, record: AuditRecord) -> None: ...
    def verify_chain(self, trace_id: str) -> object: ...  # ChainVerifyResult (duck-typed)
    def list_traces(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict]: ...
    def count_traces(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> int: ...
    def get_trace_records(self, trace_id: str) -> list[dict]: ...


@runtime_checkable
class EventSink(Protocol):
    """前端事件推送接口（API/WS 层实现，X 订阅）。"""

    def emit(self, event: StreamEvent) -> None: ...
