"""阶段4 端到端 demo 公共装配：真地板 + fake planner（不联网）。

**装配真件**（dev=c6ca02f 已闭合的地板）：
- 真 os_ops 工具集（`mcp_servers.os_ops.all_specs()`）——非桩；
- 真 PolicyEngine（`backend.app.security.PolicyEngine(DEFAULT_POLICY, registry)`）——非桩；
- 真 PrivilegeExecutor（`backend.app.executor.PrivilegeExecutor(sandbox_enabled=...)`）——非桩，
  sandbox_enabled 按平台 + env 走（默认关；VM 设 KYLIN_SANDBOX_ENABLED=1 才开）；
- 真 SqliteAuditSink（`:memory:`）——非桩，哈希链落库 + verify_chain 真过。

**fake 仅 LLM**（阶段 5 才接真 LLM 端点）：`scripted_llm` 按调用次序返回预置 Intent JSON，
既不触网也不调 LLM 客户端的修复/降级逻辑。fake planner **不参与安全判定**，仅供 demo 驱动。

**结果**：A/B/E/F 四场景在本机可全真跑通（含五道闸全链 + 真审计落库 + verify_chain）；
C/D 场景在 Windows 上沙箱关闭后真执行 systemctl/gzip 会因无命令而 fail-fast（exit_code≠0），
属"诚实不撒谎"，VM 上 KYLIN_SANDBOX_ENABLED=1 才完整闭合（沙箱 wrapper+systemd 瞬态 service）。

C3 边界：本脚本**只 import** 既有真件 + 自写 fake LLM；不重写任何策略/执行/审计逻辑。
"""

from __future__ import annotations

import json
import os
import platform
import sqlite3
from typing import Any

from backend.app.agent.orchestrator import Orchestrator
from backend.app.agent.state_machine import State
from backend.app.audit import SqliteAuditSink
from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.stream import StreamEvent
from backend.app.executor import PrivilegeExecutor
from backend.app.llm.adapter import LLMAdapter, Message
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from backend.app.security import DEFAULT_POLICY, PolicyEngine
from mcp_servers.os_ops import all_specs


def _is_sandbox_enabled() -> bool:
    """沙箱启用判定（与 `backend.app.api._fakes._SANDBOX_ENV` 一致）。

    非 Windows + env KYLIN_SANDBOX_ENABLED=="1" 才开；默认关、零行为改变。
    """
    return (
        platform.system() != "Windows"
        and os.environ.get("KYLIN_SANDBOX_ENABLED", "").strip() == "1"
    )


class CollectingEvents:
    """事件收集器（替代 `_demo_common.PrintEvents` 的 print 副作用）。

    `events` 列表按 emit 顺序累积，供 demo 脚本事后断言
    （如"REJECTED 终态必 emit rejected 事件 cause=injection"）。
    """

    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    def emit(self, event: StreamEvent) -> None:
        self.events.append(event)


class CapturingAudit:
    """审计审计器：落库真件 + 内存拷贝。

    实际落库经 `SqliteAuditSink` 完成（per-record 写 SQLite :memory: 表），
    本类同时把每条记录再 append 到 `records` 列表——供 demo 脚本事后断言
    哈希链结构（seq 连续、prev_hash 链、payload 字段）。
    """

    def __init__(self, sink: SqliteAuditSink) -> None:
        self.sink = sink
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)
        self.sink.append(record)


def scripted_llm(*intents_json: str) -> LLMAdapter:
    """按调用次序返回预置 Intent JSON 的桩 LLM（不联网、不修复/降级）。

    阶段 5 切真 LLM 时，本函数整体替换为 `get_llm` provider 即可。
    """
    seq = list(intents_json)
    calls = {"n": 0}

    async def fn(messages: list[Message]) -> str:
        _ = messages
        out = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return out

    return LLMAdapter(completion_fn=fn)


def build_e2e(
    *,
    trace_id: str,
    intents: list[str],
    sandbox_enabled: bool | None = None,
) -> tuple[Orchestrator, CollectingEvents, CapturingAudit, SqliteAuditSink]:
    """装配端到端 orchestrator：**真策略 + 真执行 + 真审计 + fake LLM**。

    - `trace_id`：审计链 trace id。
    - `intents`：fake planner 按调用次序返回的 Intent JSON 字符串列表。
    - `sandbox_enabled`：None=按 platform+env 自动判定；True/False 显式覆盖。
      （True 在 Windows 上仍会被 PrivilegeExecutor 自身 fail-closed 接受，但实际
      wrapper+systemd 不存在会失败——VM 专属场景。）

    Returns: (orchestrator, events, audit, sqlite_sink) ——events/audit 供断言，
    sqlite_sink 供 verify_chain / 篡改场景 F 直接复用。
    """
    registry = ToolRegistry(all_specs())
    sbx = _is_sandbox_enabled() if sandbox_enabled is None else sandbox_enabled
    sink = SqliteAuditSink(":memory:")
    audit = CapturingAudit(sink)
    gateway = MCPGateway(
        registry=registry,
        policy=PolicyEngine(DEFAULT_POLICY, registry),
        executor=PrivilegeExecutor(sandbox_enabled=sbx),  # type: ignore[arg-type]
    )
    orch = Orchestrator(
        llm=scripted_llm(*intents),
        gateway=gateway,
        audit=audit,  # type: ignore[arg-type]  # CapturingAudit 满足 AuditSink Protocol
        events=CollectingEvents(),
        trace_id=trace_id,
    )
    return orch, orch._events, audit, sink  # type: ignore[attr-defined]


def dump_audit(records: list[AuditRecord]) -> list[dict[str, Any]]:
    """把审计记录序列化为可 JSON 化的字典列表（供交接/报告展示）。"""
    return [
        {
            "seq": r.seq,
            "phase": r.phase,
            "prev_hash": r.prev_hash,
            "curr_hash": r.curr_hash,
            "payload": r.payload,
        }
        for r in records
    ]


def make_intent(
    *,
    intent: str,
    candidate_tools: list[dict[str, Any]],
    risk_hint: str = "medium",
    need_observation: bool = False,
    confidence: float = 0.9,
    justification: str = "stage4 demo scripted intent",
) -> str:
    """构造一段 fake planner 返回的 Intent JSON 字符串。

    调用方传 `candidate_tools=[{"name": "file.read", "args": {"path": "/etc/shadow"}}]`
    即可——schema 校验由 LLMAdapter.plan → parse_intent → Intent 强类型保证。
    """
    payload = {
        "intent": intent,
        "confidence": confidence,
        "need_observation": need_observation,
        "candidate_tools": candidate_tools,
        "risk_hint": risk_hint,
        "justification": justification,
    }
    return json.dumps(payload, ensure_ascii=False)


def collect_audit_payloads(records: list[AuditRecord], phase: str | None = None) -> list[dict]:
    """从审计记录中按 phase 抽 payload（None=全量）。"""
    if phase is None:
        return [r.payload for r in records]
    return [r.payload for r in records if r.phase == phase]


def find_audit_payload(records: list[AuditRecord], *, contains: dict[str, Any]) -> dict | None:
    """在审计记录中找第一条 payload 是 `contains` 超集的记录（值相等 + 全键覆盖）。"""
    for r in records:
        if all(r.payload.get(k) == v for k, v in contains.items()):
            return r.payload
    return None


__all__ = [
    "CollectingEvents",
    "CapturingAudit",
    "scripted_llm",
    "build_e2e",
    "dump_audit",
    "make_intent",
    "collect_audit_payloads",
    "find_audit_payload",
    "State",
    "CandidateTool",
    "sqlite3",  # 暴露供场景 F 真篡改用
]
