"""Orchestrator 的依赖注入端口（运行时接口，非数据契约）。

这些是 orchestrator 与其协作者之间的**行为接口**，与 contracts/ 的数据模型分层：
- PolicyEngine 已在 contracts/policy.py（D 实现），此处再导出方便集中引用。
- Executor / AuditSink 由 D 实现（backend/app/{executor,audit}）；此处仅给 Protocol，
  orchestrator 依赖注入并空跑，L 不实现。
- EventSink 由 orchestrator/API 层提供（推流给前端 X）。

放在 agent/ 而非 contracts/：这些是运行时协作接口，非冻结的数据事实来源，
改动不触发契约冻结纪律。若 D 需要不同签名，先对齐再调整（不擅自改）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyEngine
from backend.app.contracts.stream import StreamEvent
from backend.app.contracts.untrusted import ToolResult

__all__ = ["PolicyEngine", "Executor", "AuditSink", "EventSink"]


@runtime_checkable
class Executor(Protocol):
    """特权代理执行器接口（D 实现）。

    放行后的工具调用交由此接口在 systemd 沙箱内执行；orchestrator 不直接跑命令。
    返回 ToolResult；执行失败以非 0 exit_code 表达（方案 B：失败也算"执行完成"，
    由 VERIFIED 阶段判定），系统级故障可抛异常由 orchestrator 转 error 事件。
    """

    async def execute(self, tool: CandidateTool) -> ToolResult: ...


@runtime_checkable
class AuditSink(Protocol):
    """审计落库接口（D 的 audit_logger 实现）。

    orchestrator 在每个状态转移点产 AuditRecord 并 append；落库与哈希链校验归 D。
    """

    def append(self, record: AuditRecord) -> None: ...


@runtime_checkable
class EventSink(Protocol):
    """前端事件推送接口（API/WS 层实现，X 订阅）。"""

    def emit(self, event: StreamEvent) -> None: ...
