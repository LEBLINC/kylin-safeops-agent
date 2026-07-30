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


def test_h2_terminal_audit_precedes_state_flip() -> None:
    """终态的审计/事件必须早于状态翻转（AST 级不变量守门）。

    背景：H-7 把审计落库挪进线程池后，"先 _goto 再 await _append_audit"的旧顺序
    留下观测窗口——外部轮询到终态时最后一条审计尚在途，verify_chain 只见 8 条而
    COUNT(*) 已 9 条，实测约 1/3 概率 flaky（H-2 有界队列改动使其暴露）。

    修复口径：终态一律"审计 + emit 先行，最后 _goto"。之六十七 H15 已在
    WAIT_APPROVAL 分支确立该模式，之七十五 H-2 推广到 FINISHED / REJECTED×3；
    FAILED 在 R-2 落地时即已遵守。

    实现用 AST 而非字符串 rfind：rfind 会跨分支命中上一个分支的 _append_audit，
    导致把错误顺序也判为通过（写这条断言时初版就栽在这上，变异测试才抓出来）。
    改为在**同一语句块**内比较两者的相对下标，并已变异验证：把任一终态改回
    "先 _goto 再 audit"，本用例即转红。
    """
    import ast
    import inspect

    from backend.app.agent import orchestrator as orch_mod

    tree = ast.parse(inspect.getsource(orch_mod))
    terminals = {"FINISHED", "REJECTED", "FAILED"}
    checked = 0

    def _is_goto_terminal(node: ast.stmt) -> str | None:
        """该语句是否为 self._goto(State.<终态>)。"""
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            return None
        call = node.value
        if not (isinstance(call.func, ast.Attribute) and call.func.attr == "_goto"):
            return None
        for arg in call.args:
            if isinstance(arg, ast.Attribute) and arg.attr in terminals:
                return arg.attr
        return None

    def _is_await_append_audit(node: ast.stmt) -> bool:
        """该语句是否为 await self._append_audit(...)。"""
        inner = node.value if isinstance(node, ast.Expr) else None
        if not isinstance(inner, ast.Await) or not isinstance(inner.value, ast.Call):
            return False
        func = inner.value.func
        return isinstance(func, ast.Attribute) and func.attr == "_append_audit"

    def _walk_blocks(node: ast.AST) -> None:
        """遍历每个语句块（函数体 / if 体 / else 体 ...），块内比较顺序。"""
        nonlocal checked
        for _field, value in ast.iter_fields(node):
            if not isinstance(value, list):
                continue
            stmts = [s for s in value if isinstance(s, ast.stmt)]
            goto_idx = {}
            audit_idx = []
            for i, stmt in enumerate(stmts):
                name = _is_goto_terminal(stmt)
                if name is not None:
                    goto_idx[i] = name
                if _is_await_append_audit(stmt):
                    audit_idx.append(i)
            for i, name in goto_idx.items():
                checked += 1
                # 要求"紧邻"而非仅"之前存在"：同一块里往往有多条 _append_audit
                # （如 _execute_batch 里 EXECUTED/VERIFIED 各一条），只要求"之前有"
                # 会让"先 _goto 再 audit"的错误顺序照样通过（初版正是如此，变异测试抓出）。
                # 判据：_goto 与其后紧邻语句之间不得插入 await _append_audit，
                # 且该终态自身的 audit 必须落在 _goto 之前的 1~3 条语句内。
                nearby_before = [j for j in audit_idx if i - 3 <= j < i]
                after = [j for j in audit_idx if j > i]
                assert nearby_before, (
                    f"{name}: _goto 之前紧邻处没有 await self._append_audit——"
                    "终态必须先落审计再翻状态，否则外部观测到终态时审计仍在途"
                )
                assert not any(j == i + 1 for j in after), (
                    f"{name}: _goto 之后紧跟 await self._append_audit——"
                    "顺序颠倒，外部会在审计落库前观测到终态"
                )
        for child in ast.iter_child_nodes(node):
            _walk_blocks(child)

    _walk_blocks(tree)
    assert checked >= 4, f"应至少覆盖 FINISHED + REJECTED×3 + FAILED，实际只查到 {checked} 处"
