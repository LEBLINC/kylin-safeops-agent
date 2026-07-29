"""D3-a 状态机纯定义测试：状态名、分支转移、终态、可达性、与契约5 phase 对齐。"""

from __future__ import annotations

from backend.app.agent.state_machine import (
    INITIAL_STATE,
    TERMINAL_STATES,
    State,
    allowed_transitions,
    is_terminal,
    is_valid_transition,
)
from backend.app.contracts.audit import AuditRecord

# 手册 §3.4 的状态名清单（事实来源，须原样）。
_MANUAL_STATES = {
    "RECEIVED",
    "INTENT_PARSED",
    "CONTEXT_COLLECTED",
    "PLAN_GENERATED",
    "POLICY_CHECKED",
    "WAIT_APPROVAL",
    "REJECTED",
    "EXECUTING",
    "EXECUTED",
    "VERIFIED",
    "FINISHED",
    # 之七十五 R-2 增补：执行期系统故障终态（≠ REJECTED 的安全拒绝语义）
    "FAILED",
}


def test_states_match_manual_exactly() -> None:
    assert {s.value for s in State} == _MANUAL_STATES
    # 名值一致，便于直接用作 phase 字符串
    assert all(s.name == s.value for s in State)


def test_initial_state() -> None:
    assert INITIAL_STATE is State.RECEIVED


def test_policy_checked_three_branches() -> None:
    """POLICY_CHECKED 三出口对应契约3 Decision：allow/confirm/deny。"""
    nxt = allowed_transitions(State.POLICY_CHECKED)
    assert nxt == frozenset({State.EXECUTING, State.WAIT_APPROVAL, State.REJECTED})


def test_wait_approval_two_branches() -> None:
    """WAIT_APPROVAL：批准→EXECUTING，拒绝→REJECTED。"""
    nxt = allowed_transitions(State.WAIT_APPROVAL)
    assert nxt == frozenset({State.EXECUTING, State.REJECTED})


def test_terminal_states() -> None:
    assert TERMINAL_STATES == frozenset({State.REJECTED, State.FINISHED, State.FAILED})
    assert is_terminal(State.REJECTED)
    assert is_terminal(State.FINISHED)
    assert is_terminal(State.FAILED)
    assert not is_terminal(State.RECEIVED)


def test_r2_executing_two_branches() -> None:
    """R-2: EXECUTING 两出口——正常 → EXECUTED，系统故障 → FAILED。"""
    assert allowed_transitions(State.EXECUTING) == frozenset({State.EXECUTED, State.FAILED})
    assert is_valid_transition(State.EXECUTING, State.FAILED)
    # FAILED 是终态，不得回流
    assert not is_valid_transition(State.FAILED, State.EXECUTING)
    # FAILED 只能由 EXECUTING 到达（系统故障仅发生在执行期）
    sources = [s for s in State if is_valid_transition(s, State.FAILED)]
    assert sources == [State.EXECUTING], f"FAILED 只应由 EXECUTING 可达，实际 {sources}"


def test_r2_audit_retention_terminal_phases_in_sync() -> None:
    """R-2: audit 域的终态字面值必须与状态机 TERMINAL_STATES 同步.

    audit_logger 刻意不 import agent 模块（域解耦），改用字面常量；本用例是
    两者不漂移的唯一保障——漏掉 FAILED 会让故障 trace 永远算 in-flight。
    """
    from backend.app.audit.audit_logger import _TERMINAL_PHASES

    assert set(_TERMINAL_PHASES) == {s.value for s in TERMINAL_STATES}


def test_valid_and_invalid_transitions() -> None:
    assert is_valid_transition(State.RECEIVED, State.INTENT_PARSED)
    # 输入闸 deny（D-10 high 注入）：RECEIVED → REJECTED 是合法新增转移（拦在 LLM 之前）
    assert is_valid_transition(State.RECEIVED, State.REJECTED)
    # INTENT_PARSED 可跳过观测直达规划，也可先采集上下文
    assert is_valid_transition(State.INTENT_PARSED, State.PLAN_GENERATED)
    assert is_valid_transition(State.INTENT_PARSED, State.CONTEXT_COLLECTED)
    # 非法：跳过策略检查直接执行
    assert not is_valid_transition(State.PLAN_GENERATED, State.EXECUTING)
    # 非法：终态无出边
    assert not is_valid_transition(State.FINISHED, State.RECEIVED)
    assert not is_valid_transition(State.REJECTED, State.EXECUTING)


def test_happy_path_chain_is_valid() -> None:
    """allow 直放行的主链路逐跳合法。"""
    path = [
        State.RECEIVED,
        State.INTENT_PARSED,
        State.CONTEXT_COLLECTED,
        State.PLAN_GENERATED,
        State.POLICY_CHECKED,
        State.EXECUTING,
        State.EXECUTED,
        State.VERIFIED,
        State.FINISHED,
    ]
    assert all(is_valid_transition(a, b) for a, b in zip(path, path[1:], strict=False))


def test_all_states_reachable_from_initial() -> None:
    """从 RECEIVED 出发可达全部状态（无孤岛）。"""
    seen: set[State] = set()
    frontier = [INITIAL_STATE]
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        frontier.extend(allowed_transitions(cur))
    assert seen == set(State)


def test_state_value_usable_as_audit_phase() -> None:
    """状态 .value 可直接作为契约5 AuditRecord.phase。"""
    rec = AuditRecord(
        trace_id="t1",
        seq=0,
        phase=State.POLICY_CHECKED.value,
        payload={},
        prev_hash="0" * 64,
        curr_hash="x",
    )
    assert rec.phase == "POLICY_CHECKED"
