"""Orchestrator：串状态机 + 逐点 emit/audit（手册 §3.4）。

职责边界（铁律）：
- 只规划/编排，不直接执行命令（执行走注入的 Executor，D 实现）。
- 每个状态转移点产契约5 AuditRecord（哈希链）并 append；同时 emit 契约6 audit_appended。
- 阶段性前端事件按状态**逐点判定** EventType，不套公式（state 与 EventType 非一一对应：
  RECEIVED/REJECTED/FINISHED 无独立前端事件，仅产审计）。
- 工具结果回喂前强制 is_untrusted 包裹（结果闸；Executor 返回的 ToolResult 默认即 True）。
- 高危(confirm)必经 WAIT_APPROVAL，等外部审批回执再 EXECUTING；deny→REJECTED 终止。
- 方案 B：执行失败以 ToolResult.exit_code 承载，由 VERIFIED 判定，不新增失败状态。
- LLM 网络异常在规划处 try → emit error 事件并终止（不静默降级为仅观测）。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence

import httpx

from backend.app.agent.ports import AuditSink, EventSink, Executor, PolicyEngine
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

# 裁决严格度排序：deny 最严，allow 最宽。聚合多候选工具时取最严。
_DECISION_RANK: dict[Decision, int] = {"allow": 0, "confirm": 1, "deny": 2}


def most_restrictive(verdicts: Sequence[PolicyVerdict]) -> PolicyVerdict:
    """从多个裁决里取最严的一个（deny > confirm > allow）。"""
    return max(verdicts, key=lambda v: _DECISION_RANK[v.decision])


class Orchestrator:
    """单次请求的状态机驱动器。

    协作者依赖注入：policy/executor 由 D 实现，audit/event sink 由 D / API 层提供，
    llm 为 D2-b 的网关。本类不实现它们，只编排。
    """

    def __init__(
        self,
        *,
        llm: LLMAdapter,
        policy: PolicyEngine,
        executor: Executor,
        audit: AuditSink,
        events: EventSink,
        trace_id: str | None = None,
    ) -> None:
        self._llm = llm
        self._policy = policy
        self._executor = executor
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

        # 观测分支（need_observation）：骨架暂不接真工具，仅占位空观测
        if intent.need_observation:
            self._goto(State.CONTEXT_COLLECTED)
            self._append_audit({"observations": []})
            self._emit("observation", {"results": []})

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

        return await self._branch_on_verdict(verdict, intent.candidate_tools)

    def _evaluate(self, tools: Sequence[CandidateTool]) -> PolicyVerdict:
        """对候选工具逐个走策略引擎，取最严裁决；无候选 → 合成一个 deny。"""
        if not tools:
            return PolicyVerdict(
                decision="deny",
                final_risk="R0",
                matched_rules=[],
                reason="no candidate tools to execute",
                approval_required=False,
            )
        verdicts = [self._policy.evaluate(t) for t in tools]
        # 记住首个可执行工具供 EXECUTING 用（骨架：单工具路径）
        self._pending_tool = tools[0]
        return most_restrictive(verdicts)

    async def _branch_on_verdict(
        self, verdict: PolicyVerdict, tools: Sequence[CandidateTool]
    ) -> State:
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
        return await self._execute_and_verify()

    async def resume(self, approved: bool) -> State:
        """WAIT_APPROVAL 续跑：批准→EXECUTING 链，拒绝→REJECTED。"""
        if self.state is not State.WAIT_APPROVAL:
            raise RuntimeError(f"resume only valid in WAIT_APPROVAL, got {self.state.value}")
        if not approved:
            self._goto(State.REJECTED)
            self._append_audit({"decision": "deny", "approval_required": True})
            return self.state
        return await self._execute_and_verify()

    async def _execute_and_verify(self) -> State:
        """EXECUTING → EXECUTED → VERIFIED → FINISHED。

        方案 B：执行失败以 exit_code 承载，由 VERIFIED 判定，不新增失败状态。
        系统级故障（执行器抛异常）→ error 事件并终止。
        """
        assert self._pending_tool is not None  # 进入执行必有计划
        tool = self._pending_tool

        self._goto(State.EXECUTING)
        self._append_audit({"tool_plan": [tool.model_dump()]})
        self._emit("executing", {"tool": tool.name})

        try:
            result = await self._executor.execute(tool)
        except Exception as exc:  # noqa: BLE001 执行器系统级故障 → error 事件
            self._emit("error", {"message": str(exc), "phase": self.state.value})
            return self.state

        # 结果闸：强制不可信标记（防 Executor 实现遗漏）
        if not result.is_untrusted:
            result = result.model_copy(update={"is_untrusted": True})

        self._goto(State.EXECUTED)
        self._append_audit({"tool_plan": [tool.model_dump()]})
        self._emit("tool_result", {"result": result.model_dump()})

        # VERIFIED：方案 B 在此判定成功/失败
        ok = result.exit_code == 0
        self._goto(State.VERIFIED)
        self._append_audit({"decision": "verified", "observations": [result.exit_code]})
        self._emit("verified", {"summary": "ok" if ok else "tool exited non-zero"})

        self._goto(State.FINISHED)
        self._append_audit({"decision": "finished"})
        return self.state
