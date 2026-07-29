"""Orchestrator 状态机定义（手册 §3.4）。

纯定义层：状态枚举 + 合法转移表 + 校验函数。**无 IO**，不 emit/audit/plan，
不与契约6 EventType 做硬映射（每个转移点 emit 哪个 EventType 由 orchestrator
逐点判定，不套公式——状态与 EventType 非一一对应）。

状态名是事实来源，照 §3.4 原样，须能与契约5 AuditRecord.phase 对齐：
    RECEIVED → INTENT_PARSED → CONTEXT_COLLECTED → PLAN_GENERATED → POLICY_CHECKED
    → WAIT_APPROVAL / REJECTED / EXECUTING → EXECUTED → VERIFIED → FINISHED

之七十五 R-2 增补 FAILED：EXECUTING 期系统级故障（gateway 抛异常 / 二次过闸拦下）
此前只 emit error 就 return，状态永久停在 EXECUTING——既不落审计也不闭合 trace，
retention 视其为 in-flight 永不清理，SSE 靠 runner 兜底关闭而非终态语义。
FAILED 与 REJECTED 语义严格区分：REJECTED = 安全决策拒绝（策略/审批/注入），
FAILED = 系统故障，两者不得混用（混用会污染安全叙事）。
"""

from __future__ import annotations

from enum import Enum


class State(str, Enum):
    """状态机状态（手册 §3.4 + 之七十五 R-2 增补 FAILED）。

    继承 str 使 .value 可直接用作契约5 AuditRecord.phase 字符串。
    """

    RECEIVED = "RECEIVED"
    INTENT_PARSED = "INTENT_PARSED"
    CONTEXT_COLLECTED = "CONTEXT_COLLECTED"
    PLAN_GENERATED = "PLAN_GENERATED"
    POLICY_CHECKED = "POLICY_CHECKED"
    WAIT_APPROVAL = "WAIT_APPROVAL"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    FINISHED = "FINISHED"
    #: 之七十五 R-2：执行期系统故障终态（≠ REJECTED 的安全拒绝语义）。
    FAILED = "FAILED"


# 合法转移表：显式建模分支，不做线性链。
#
# 关键分支（须与契约3 Decision 对齐，供 orchestrator 接策略裁决时落地）：
#   RECEIVED 两出口：
#       正常        → INTENT_PARSED
#       输入闸 deny  → REJECTED（D-10 提示注入检测命中 high，拦在 LLM plan 之前）
#   POLICY_CHECKED 三出口：
#       allow   → EXECUTING
#       confirm → WAIT_APPROVAL
#       deny    → REJECTED
#   WAIT_APPROVAL 两出口：
#       批准    → EXECUTING
#       拒绝    → REJECTED
#   EXECUTING 两出口（R-2）：
#       正常        → EXECUTED
#       系统级故障   → FAILED（gateway 抛异常 / 二次过闸拦下）
#
# 终态（无出边）：REJECTED、FINISHED、FAILED。
_TRANSITIONS: dict[State, frozenset[State]] = {
    State.RECEIVED: frozenset({State.INTENT_PARSED, State.REJECTED}),
    State.INTENT_PARSED: frozenset({State.CONTEXT_COLLECTED, State.PLAN_GENERATED}),
    State.CONTEXT_COLLECTED: frozenset({State.PLAN_GENERATED}),
    State.PLAN_GENERATED: frozenset({State.POLICY_CHECKED}),
    State.POLICY_CHECKED: frozenset({State.EXECUTING, State.WAIT_APPROVAL, State.REJECTED}),
    State.WAIT_APPROVAL: frozenset({State.EXECUTING, State.REJECTED}),
    State.REJECTED: frozenset(),
    State.EXECUTING: frozenset({State.EXECUTED, State.FAILED}),
    State.EXECUTED: frozenset({State.VERIFIED}),
    State.VERIFIED: frozenset({State.FINISHED}),
    State.FINISHED: frozenset(),
    State.FAILED: frozenset(),
}

#: 终态集合：无任何合法出边。
TERMINAL_STATES: frozenset[State] = frozenset({s for s, nxt in _TRANSITIONS.items() if not nxt})

#: 状态机入口。
INITIAL_STATE: State = State.RECEIVED


def allowed_transitions(state: State) -> frozenset[State]:
    """返回 state 的所有合法后继状态（终态返回空集）。"""
    return _TRANSITIONS[state]


def is_valid_transition(src: State, dst: State) -> bool:
    """判断 src → dst 是否为合法转移。"""
    return dst in _TRANSITIONS[src]


def is_terminal(state: State) -> bool:
    """判断 state 是否为终态（无合法出边）。"""
    return state in TERMINAL_STATES
