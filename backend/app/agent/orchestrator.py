"""Orchestrator：串状态机 + 逐点 emit/audit（手册 §3.4）。

职责边界（铁律）：
- 只规划/编排，不直接执行命令（执行经注入的 MCPGateway 走完整三道闸 + 结果闸）。
- 每个状态转移点产契约5 AuditRecord（哈希链）并 append；同时 emit 契约6 audit_appended。
- 阶段性前端事件按状态**逐点判定** EventType，不套公式（state 与 EventType 非一一对应：
  RECEIVED/REJECTED/FINISHED 无独立前端事件，仅产审计）。
- 工具结果回喂前强制 is_untrusted 包裹（结果闸；gateway 已强制，orchestrator 不再裸调 executor）。
- 高危(confirm)必经 WAIT_APPROVAL，等外部审批回执再 EXECUTING；deny→REJECTED 终止。
- 方案 B：执行失败以 ToolResult.exit_code 承载，由 VERIFIED 判定，不新增失败状态。
- LLM 网络异常在规划处 try → emit error 事件并终止（不静默降级为仅观测）。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence

import httpx

from backend.app.agent.ports import AuditSink, EventSink
from backend.app.agent.state_machine import (
    INITIAL_STATE,
    State,
    is_valid_transition,
)
from backend.app.contracts.audit import GENESIS_HASH, AuditRecord, compute_curr_hash
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import Decision, PolicyVerdict
from backend.app.contracts.stream import EventType, StreamEvent
from backend.app.llm.adapter import LLMAdapter, Message
from backend.app.mcp.gateway import MCPGateway

# 裁决严格度排序：deny 最严，allow 最宽。聚合多候选工具时取最严。
_DECISION_RANK: dict[Decision, int] = {"allow": 0, "confirm": 1, "deny": 2}


def most_restrictive(verdicts: Sequence[PolicyVerdict]) -> PolicyVerdict:
    """从多个裁决里取最严的一个（deny > confirm > allow）。"""
    return max(verdicts, key=lambda v: _DECISION_RANK[v.decision])


class Orchestrator:
    """单次请求的状态机驱动器。

    协作者依赖注入：gateway(MCPGateway，封装 registry+policy+executor 三道闸+结果闸)、
    audit/event sink（D / API 层），llm 为 D2-b 的网关。本类不实现它们，只编排。
    """

    def __init__(
        self,
        *,
        llm: LLMAdapter,
        gateway: MCPGateway,
        audit: AuditSink,
        events: EventSink,
        trace_id: str | None = None,
    ) -> None:
        self._llm = llm
        self._gateway = gateway
        self._audit = audit
        self._events = events
        self.trace_id = trace_id or uuid.uuid4().hex
        self.state: State = INITIAL_STATE
        self._seq = 0
        self._prev_hash = GENESIS_HASH
        # 暂存供 resume 使用的已放行/待审工具计划
        self._pending_tool: CandidateTool | None = None

    # ---- 内部原语：转移 / 审计 / 事件（显式，不套公式）-------------------

    def _goto(self, dst: State) -> None:
        """校验并执行状态转移；非法转移即编程错误，直接抛。"""
        if not is_valid_transition(self.state, dst):
            raise RuntimeError(f"illegal transition {self.state.value} -> {dst.value}")
        self.state = dst

    def _append_audit(self, payload: dict) -> AuditRecord:
        """在当前状态产一条哈希链审计记录并落库，同时 emit audit_appended。

        phase = 当前状态名；payload 为结构化推理摘要（手册固定字段子集）。
        """
        curr_hash = compute_curr_hash(self._prev_hash, payload)
        record = AuditRecord(
            trace_id=self.trace_id,
            seq=self._seq,
            phase=self.state.value,
            payload=payload,
            prev_hash=self._prev_hash,
            curr_hash=curr_hash,
        )
        self._audit.append(record)
        self._prev_hash = curr_hash
        self._seq += 1
        # 审计增长本身是一个流事件（与状态无关，统一推送）
        self._emit("audit_appended", {"seq": record.seq, "curr_hash": record.curr_hash})
        return record

    def _emit(self, type_: EventType, data: dict) -> None:
        """推送一条前端事件。EventType 由调用点显式给定，不由状态推导。"""
        self._events.emit(
            StreamEvent(trace_id=self.trace_id, type=type_, ts=time.time(), data=data)
        )

    # ---- 主流程 -----------------------------------------------------------

    async def run(self, messages: Sequence[Message], user_intent: str = "") -> State:
        """驱动状态机从 RECEIVED 走到终态或暂停于 WAIT_APPROVAL。

        返回停止时的状态：FINISHED / REJECTED（终态）或 WAIT_APPROVAL（待审批，调 resume 续跑）。
        """
        # RECEIVED：仅审计，无独立前端事件
        self._append_audit({"user_intent": user_intent})

        # 规划：LLM 网络异常 → error 事件并终止（不静默降级）
        try:
            intent = await self._llm.plan(messages)
        except httpx.HTTPError as exc:
            self._emit("error", {"message": str(exc), "phase": self.state.value})
            return self.state

        self._goto(State.INTENT_PARSED)
        self._append_audit({"user_intent": intent.intent, "risk_level": intent.risk_hint})
        self._emit("intent_parsed", {"intent": intent.model_dump()})

        # 观测分支（need_observation）：经 gateway 调只读工具采集上下文。
        # gateway 三道闸保护：未注册/结构非法/非 allow 的工具不会执行；
        # 只把 allow 且成功执行的只读结果计入 observations（已被结果闸标记 is_untrusted）。
        if intent.need_observation:
            self._goto(State.CONTEXT_COLLECTED)
            observations = await self._collect_observations(intent.candidate_tools)
            self._append_audit({"observations": [o["exit_code"] for o in observations]})
            self._emit("observation", {"results": observations})

        # 规划完成
        self._goto(State.PLAN_GENERATED)
        tool_plan = [t.model_dump() for t in intent.candidate_tools]
        self._append_audit({"tool_plan": tool_plan})
        self._emit("plan_generated", {"candidate_tools": tool_plan})

        # 策略裁决：逐候选评估取最严；无候选则直接 deny（无可执行计划）
        verdict = self._evaluate(intent.candidate_tools)
        self._goto(State.POLICY_CHECKED)
        self._append_audit(
            {
                "decision": verdict.decision,
                "risk_level": verdict.final_risk,
                "approval_required": verdict.approval_required,
            }
        )
        self._emit("policy_verdict", {"verdict": verdict.model_dump()})

        return await self._branch_on_verdict(verdict)

    async def _collect_observations(self, tools: Sequence[CandidateTool]) -> list[dict]:
        """经 gateway 调只读工具采集观测；只收 allow 且执行成功的结果。

        防御纵深：观测阶段**只执行注册表标记为只读(R0/R1)的工具**——即便策略误把
        变更工具放行，观测阶段也绝不触发变更（变更必须走 POLICY_CHECKED→WAIT_APPROVAL）。
        不传 approved：confirm/deny 工具在此不会执行。系统级异常被吞并跳过（尽力而为）。
        """
        results: list[dict] = []
        for tool in tools:
            if not self._gateway.is_read_only(tool):
                continue  # 非只读工具不在观测阶段执行（防御纵深）
            try:
                outcome = await self._gateway.call(tool)
            except Exception:  # noqa: BLE001 观测尽力而为，单个工具故障不阻断规划
                continue
            if outcome.executed and outcome.result is not None:
                results.append(outcome.result.model_dump())
        return results

    def _evaluate(self, tools: Sequence[CandidateTool]) -> PolicyVerdict:
        """经 gateway 逐候选裁决（含注册+结构校验+策略），取最严；无候选 → 合成 deny。"""
        if not tools:
            return PolicyVerdict(
                decision="deny",
                final_risk="R0",
                matched_rules=[],
                reason="no candidate tools to execute",
                approval_required=False,
            )
        verdicts = [self._gateway.evaluate(t) for t in tools]
        # 记住首个候选工具供 EXECUTING 用（骨架：单工具路径）
        self._pending_tool = tools[0]
        return most_restrictive(verdicts)

    async def _branch_on_verdict(self, verdict: PolicyVerdict) -> State:
        """POLICY_CHECKED 三出口：allow→执行、confirm→待审批、deny→拒绝。"""
        if verdict.decision == "deny":
            self._goto(State.REJECTED)
            self._append_audit({"decision": "deny", "approval_required": False})
            return self.state

        if verdict.decision == "confirm":
            self._goto(State.WAIT_APPROVAL)
            self._append_audit({"decision": "confirm", "approval_required": True})
            self._emit(
                "await_approval",
                {"approval_role": verdict.approval_role, "reason": verdict.reason},
            )
            return self.state  # 暂停，等 resume()

        # allow
        return await self._execute_and_verify(approved=False)

    async def resume(self, approved: bool) -> State:
        """WAIT_APPROVAL 续跑：批准→EXECUTING 链，拒绝→REJECTED。"""
        if self.state is not State.WAIT_APPROVAL:
            raise RuntimeError(f"resume only valid in WAIT_APPROVAL, got {self.state.value}")
        if not approved:
            self._goto(State.REJECTED)
            self._append_audit({"decision": "deny", "approval_required": True})
            return self.state
        # 批准：confirm 工具经 gateway 时需带 approved=True 才放行
        return await self._execute_and_verify(approved=True)

    async def _execute_and_verify(self, *, approved: bool) -> State:
        """EXECUTING → EXECUTED → VERIFIED → FINISHED，执行经 gateway 完整三道闸。

        方案 B：执行失败以 exit_code 承载，由 VERIFIED 判定，不新增失败状态。
        gateway 拦下（理论不应发生，因 _evaluate 已放行；防御纵深）→ emit error 并终止。
        系统级故障（gateway/executor 抛异常）→ error 事件并终止。
        """
        assert self._pending_tool is not None  # 进入执行必有计划
        tool = self._pending_tool

        self._goto(State.EXECUTING)
        self._append_audit({"tool_plan": [tool.model_dump()]})
        self._emit("executing", {"tool": tool.name})

        try:
            outcome = await self._gateway.call(tool, approved=approved)
        except Exception as exc:  # noqa: BLE001 gateway/执行器系统级故障 → error 事件
            self._emit("error", {"message": str(exc), "phase": self.state.value})
            return self.state

        # 防御纵深：gateway 二次过闸若拦下（与 _evaluate 不一致），不推进、emit error
        if not outcome.executed or outcome.result is None:
            self._emit(
                "error",
                {"message": f"gateway blocked: {outcome.reason}", "phase": self.state.value},
            )
            return self.state

        result = outcome.result  # gateway 已强制 is_untrusted=True（结果闸）

        self._goto(State.EXECUTED)
        self._append_audit({"tool_plan": [tool.model_dump()]})
        self._emit("tool_result", {"result": result.model_dump()})

        # VERIFIED：方案 B 在此判定成功/失败
        ok = result.exit_code == 0
        self._goto(State.VERIFIED)
        self._append_audit(
            {"verify_result": "ok" if ok else "non_zero", "observations": [result.exit_code]}
        )
        self._emit("verified", {"summary": "ok" if ok else "tool exited non-zero"})

        self._goto(State.FINISHED)
        self._append_audit({"verify_result": "ok" if ok else "non_zero"})
        return self.state
