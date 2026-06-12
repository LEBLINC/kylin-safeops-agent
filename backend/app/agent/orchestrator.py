"""Orchestrator：串状态机 + 逐点 emit/audit（手册 §3.4）。

职责边界（铁律）：
- 只规划/编排，不直接执行命令（执行经注入的 MCPGateway 走完整三道闸 + 结果闸）。
- 每个状态转移点产契约5 AuditRecord（哈希链）并 append；同时 emit 契约6 audit_appended。
- 阶段性前端事件按状态**逐点判定** EventType（state 与 EventType 非一一对应）：
  RECEIVED/FINISHED 无独立前端事件仅产审计；REJECTED 终态显式 emit "rejected"（L-6 方案B）。
- 工具结果回喂前强制 is_untrusted 包裹（结果闸；gateway 已强制，orchestrator 不再裸调 executor）。
- 高危(confirm)必经 WAIT_APPROVAL，等外部审批回执再 EXECUTING；deny→REJECTED 终止。
- 方案 B：执行失败以 ToolResult.exit_code 承载，由 VERIFIED 判定，不新增失败状态。
- LLM 网络异常在规划处 try → emit error 事件并终止（不静默降级为仅观测）。
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Sequence

import httpx

from backend.app.agent.ports import AuditSink, EventSink
from backend.app.agent.rca import NullRCA, RCAEngine
from backend.app.agent.state_machine import (
    INITIAL_STATE,
    State,
    is_valid_transition,
)
from backend.app.contracts.audit import GENESIS_HASH, AuditRecord, compute_curr_hash
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import Decision, PolicyVerdict
from backend.app.contracts.stream import EventType, StreamEvent
from backend.app.contracts.untrusted import ToolResult
from backend.app.llm.adapter import LLMAdapter, Message
from backend.app.llm.feedback import wrap_many_for_feedback
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
        rca: RCAEngine | None = None,
        trace_id: str | None = None,
        max_observation_rounds: int = 3,
    ) -> None:
        self._llm = llm
        self._gateway = gateway
        self._audit = audit
        self._events = events
        self._rca: RCAEngine = rca or NullRCA()
        self.trace_id = trace_id or uuid.uuid4().hex
        self.state: State = INITIAL_STATE
        self._seq = 0
        self._prev_hash = GENESIS_HASH
        # 观测→re-plan 多轮上限（有界，防死循环）
        self._max_observation_rounds = max(1, max_observation_rounds)
        # 暂存供 resume 使用的执行批次（原子计划：审批后整批执行）
        self._batch: list[CandidateTool] | None = None
        # 累积本次请求的所有不可信结果（观测+执行），供 RCA 接入点使用
        self._evidence: list[ToolResult] = []

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

        # 观测分支（need_observation）：有界多轮 observe→re-plan（手册，防死循环）。
        # 在 CONTEXT_COLLECTED 内循环（不新增状态、不重复 _goto）：每轮经 gateway 只读防御
        # 纵深采集观测 → 安全封装回喂 → 二次规划；满足终止条件或达上限后进入 PLAN_GENERATED。
        # 解决"观测与行动共用 candidate_tools、只读工具双执行"：观测用各轮 intent 的只读候选，
        # 行动用最终规划 action_intent 的候选（二者分离）。
        action_intent = intent
        if intent.need_observation:
            self._goto(State.CONTEXT_COLLECTED)
            convo: list[Message] = list(messages)
            current = intent
            for _round in range(self._max_observation_rounds):
                # 观测当前计划的（只读）候选工具；记录指纹用于"无推进"截断
                observed_key = self._candidates_key(current.candidate_tools)
                observations = await self._collect_observations(current.candidate_tools)
                self._evidence.extend(observations)
                self._append_audit({"observations": [o.exit_code for o in observations]})
                self._emit("observation", {"results": [o.model_dump() for o in observations]})
                # 把观测结果作为不可信数据回喂，二次规划
                try:
                    feedback = wrap_many_for_feedback(observations)
                    convo = [*convo, {"role": "user", "content": feedback}]
                    current = await self._llm.plan(convo)
                except httpx.HTTPError as exc:
                    self._emit("error", {"message": str(exc), "phase": self.state.value})
                    return self.state
                action_intent = current
                # 终止条件（任一即停，进入规划）：
                #   不再需要观测 / 无候选工具 / 候选与刚观测的一致（planner 未推进，防循环）。
                # 达到 _max_observation_rounds 时循环自然退出（强制进入规划），双重防死循环。
                if not current.need_observation:
                    break
                if not current.candidate_tools:
                    break
                if self._candidates_key(current.candidate_tools) == observed_key:
                    break

        # 规划完成（行动计划 = action_intent 的候选工具）
        self._goto(State.PLAN_GENERATED)
        tool_plan = [t.model_dump() for t in action_intent.candidate_tools]
        self._append_audit({"tool_plan": tool_plan})
        self._emit("plan_generated", {"candidate_tools": tool_plan})

        # 策略裁决：逐候选各自裁决（含注册+结构校验+策略）。
        # 无候选 → 合成 deny；有候选 → 整批决策 = 最严裁决（deny>confirm>allow）。
        per_tool = self._evaluate_all(action_intent.candidate_tools)
        batch_verdict = self._batch_decision(per_tool)
        self._goto(State.POLICY_CHECKED)
        self._append_audit(
            {
                "decision": batch_verdict.decision,
                "risk_level": batch_verdict.final_risk,
                "approval_required": batch_verdict.approval_required,
            }
        )
        # 逐工具裁决一并下发，前端按工具粒度展示；整批裁决决定状态机走向
        self._emit(
            "policy_verdict",
            {
                "verdict": batch_verdict.model_dump(),
                "per_tool": [{"tool": t.name, "verdict": v.model_dump()} for t, v in per_tool],
            },
        )

        return await self._branch_on_verdict(batch_verdict, per_tool)

    @staticmethod
    def _candidates_key(tools: Sequence[CandidateTool]) -> tuple[tuple[str, str], ...]:
        """候选工具的稳定指纹（名 + 规范化 args），用于判定两轮规划是否无变化（防循环）。"""
        return tuple((t.name, json.dumps(t.args, sort_keys=True)) for t in tools)

    async def _collect_observations(self, tools: Sequence[CandidateTool]) -> list[ToolResult]:
        """经 gateway 调只读工具采集观测；只收 allow 且执行成功的结果（已密封）。

        防御纵深：观测阶段**只执行注册表标记为只读(R0/R1)的工具**——即便策略误把
        变更工具放行，观测阶段也绝不触发变更（变更必须走 POLICY_CHECKED→WAIT_APPROVAL）。
        不传 approved：confirm/deny 工具在此不会执行。系统级异常被吞并跳过（尽力而为）。
        返回 ToolResult 列表，供 emit observation 与回喂二次规划共用。
        """
        results: list[ToolResult] = []
        for tool in tools:
            if not self._gateway.is_read_only(tool):
                continue  # 非只读工具不在观测阶段执行（防御纵深）
            try:
                outcome = await self._gateway.call(tool)
            except Exception:  # noqa: BLE001 观测尽力而为，单个工具故障不阻断规划
                continue
            if outcome.executed and outcome.result is not None:
                results.append(outcome.result)
        return results

    def _evaluate_all(
        self, tools: Sequence[CandidateTool]
    ) -> list[tuple[CandidateTool, PolicyVerdict]]:
        """逐候选经 gateway 裁决（含注册+结构校验+策略），返回 (工具, 裁决) 列表。"""
        return [(t, self._gateway.evaluate(t)) for t in tools]

    def _batch_decision(
        self, per_tool: Sequence[tuple[CandidateTool, PolicyVerdict]]
    ) -> PolicyVerdict:
        """整批决策（原子计划）：无候选→合成 deny；否则取最严裁决。

        most_restrictive 在此重新定位为"整批门槛"：deny>confirm>allow。
        含禁止动作(deny)的计划整体 REJECTED，不部分执行（安全优先）。
        """
        if not per_tool:
            return PolicyVerdict(
                decision="deny",
                final_risk="R0",
                matched_rules=[],
                reason="no candidate tools to execute",
                approval_required=False,
            )
        return most_restrictive([v for _, v in per_tool])

    async def _branch_on_verdict(
        self,
        batch_verdict: PolicyVerdict,
        per_tool: Sequence[tuple[CandidateTool, PolicyVerdict]],
    ) -> State:
        """POLICY_CHECKED 三出口（原子计划）：
        - deny：整批 REJECTED（含禁止动作，不部分执行）；
        - confirm：整批 WAIT_APPROVAL，面板列出所有 confirm 工具及角色；
        - allow：整批执行（全 allow）。
        """
        if batch_verdict.decision == "deny":
            denied = [t.name for t, v in per_tool if v.decision == "deny"]
            self._goto(State.REJECTED)
            self._append_audit(
                {"decision": "deny", "approval_required": False, "denied_tools": denied}
            )
            # L-6 方案B：REJECTED 终态显式结论事件（策略 deny），让前端/任意消费者收尾。
            self._emit(
                "rejected",
                {
                    "reason": batch_verdict.reason,
                    "cause": "policy_deny",
                    "denied_tools": denied,
                },
            )
            return self.state

        # 非 deny：批次内不含 deny 工具，执行集 = 全部候选工具
        self._batch = [t for t, _ in per_tool]

        if batch_verdict.decision == "confirm":
            confirm_tools = [
                {"tool": t.name, "approval_role": v.approval_role}
                for t, v in per_tool
                if v.decision == "confirm"
            ]
            self._goto(State.WAIT_APPROVAL)
            self._append_audit({"decision": "confirm", "approval_required": True})
            # 面板展示的 confirm 工具，正是批准后会执行的同一批的子集（消除错配）
            self._emit(
                "await_approval",
                {"reason": batch_verdict.reason, "tools": confirm_tools},
            )
            return self.state  # 暂停，等 resume()

        # allow：整批无需审批
        return await self._execute_batch(approved=False)

    async def resume(self, approved: bool) -> State:
        """WAIT_APPROVAL 续跑：批准→执行整批，拒绝→整批 REJECTED（原子计划）。"""
        if self.state is not State.WAIT_APPROVAL:
            raise RuntimeError(f"resume only valid in WAIT_APPROVAL, got {self.state.value}")
        if not approved:
            self._goto(State.REJECTED)
            self._append_audit({"decision": "deny", "approval_required": True})
            # L-6 方案B：REJECTED 终态显式结论事件（用户拒批）。
            self._emit(
                "rejected",
                {
                    "reason": "operator rejected the plan",
                    "cause": "user_reject",
                    "denied_tools": [],
                },
            )
            return self.state
        return await self._execute_batch(approved=True)

    async def _execute_batch(self, *, approved: bool) -> State:
        """EXECUTING → EXECUTED → VERIFIED → FINISHED，按序逐工具经 gateway 执行。

        审批面板展示的 == 实际执行的（self._batch）；每个工具各自留痕（审计+tool_result）。
        方案 B：单工具失败以 exit_code 承载，由 VERIFIED 聚合判定。
        gateway 拦下/系统级异常 → emit error 并终止（不推进）。
        approved 传给每个工具：allow 工具不需要也无害，confirm 工具靠它放行。
        """
        assert self._batch is not None  # 进入执行必有批次

        self._goto(State.EXECUTING)
        self._append_audit({"tool_plan": [t.model_dump() for t in self._batch]})
        self._emit("executing", {"tools": [t.name for t in self._batch]})

        results: list[ToolResult] = []
        for tool in self._batch:
            try:
                outcome = await self._gateway.call(tool, approved=approved)
            except Exception as exc:  # noqa: BLE001 系统级故障 → error 并终止
                self._emit("error", {"message": str(exc), "phase": self.state.value})
                return self.state
            # 防御纵深：gateway 二次过闸拦下（与裁决不一致）→ error 并终止
            if not outcome.executed or outcome.result is None:
                self._emit(
                    "error",
                    {
                        "message": f"gateway blocked {tool.name}: {outcome.reason}",
                        "phase": self.state.value,
                    },
                )
                return self.state
            result = outcome.result  # gateway 已密封（is_untrusted + 标准 wrap_token）
            results.append(result)
            self._evidence.append(result)
            # 每个工具各自留痕
            self._append_audit({"tool": tool.name, "exit_code": result.exit_code})
            self._emit("tool_result", {"result": result.model_dump()})

        self._goto(State.EXECUTED)
        self._append_audit({"executed": [t.name for t in self._batch]})

        # VERIFIED：方案 B 聚合判定——全部 exit_code==0 才算 ok
        all_ok = all(r.exit_code == 0 for r in results)
        self._goto(State.VERIFIED)
        self._append_audit(
            {
                "verify_result": "ok" if all_ok else "non_zero",
                "observations": [r.exit_code for r in results],
            }
        )
        self._emit(
            "verified",
            {"summary": "ok" if all_ok else "one or more tools exited non-zero"},
        )

        # RCA 接入点（手册 D15）：把累积证据交给注入的 RCAEngine（默认 NullRCA→空报告），
        # 非空则 emit 契约6 "rca" 事件。RCA 真实编排归 X，本处仅调起。
        report = self._rca.analyze(self._evidence)
        if report:
            self._emit("rca", {"report": report})

        self._goto(State.FINISHED)
        self._append_audit({"verify_result": "ok" if all_ok else "non_zero"})
        return self.state
