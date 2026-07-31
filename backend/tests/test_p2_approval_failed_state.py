"""P2: 审批列表不认 FAILED 终态——已批准但执行失败的单子凭空消失。

批 C 的 P1-9 给状态机增补了 FAILED 终态（执行期/规划期系统故障），
但 approvals.py 的 _match 过滤器只认三个状态：

    pending  → WAIT_APPROVAL
    approved → FINISHED
    其余     → REJECTED   （兜底 return，FAILED 落到这里但不等于 REJECTED）

于是 state=FAILED 的单子：
  - status=pending  不含（不是 WAIT_APPROVAL）
  - status=approved 不含（不是 FINISHED）
  - status=rejected 不含（不是 REJECTED）
三个列表全部查不到，只有 status=all 能看见。运维视角上"我批准的那单去哪了"
完全无法回答——这正是新增终态最容易带出的连带缺口。

处置口径：FAILED 归入 approved 列表。理由——审批动作本身已完成（批准了），
失败发生在执行期，属于"已批准单的执行结果"。归进 rejected 会污染安全叙事
（REJECTED 语义是"安全决策拒绝"，与系统故障严格区分，见 state_machine.py）。

  A-1 FAILED 单必须出现在 status=approved
  A-2 FAILED 单不得出现在 status=rejected（不污染安全拒绝语义）
  A-3 FAILED 单不得出现在 status=pending（它已是终态）
  A-4 status=all 含全部四个终态（回归锚点）
  A-5 三个既有状态归类不回归
"""

from __future__ import annotations

import pytest

from backend.app.agent.state_machine import TERMINAL_STATES, State


def _match(wanted: str, state: str) -> bool:
    """复刻 approvals.list_approvals 的 _match 判据（同一份逻辑，独立可测）。

    直接 import 不可行：_match 是 list_approvals 的内部闭包。
    本函数与实现保持同步由 A-6 结构断言守门。
    """
    from backend.app.api.routers.approvals import _classify_state

    return _classify_state(state) == wanted or wanted == "all"


def test_a1_failed_appears_in_approved() -> None:
    """A-1: FAILED 必须归入 approved——审批动作已完成，失败在执行期。"""
    assert _match(
        "approved", "FAILED"
    ), "A-1: FAILED 不在 approved 列表——已批准但执行失败的单子从审批视图消失"


def test_a2_failed_not_in_rejected() -> None:
    """A-2: FAILED 不得混进 rejected——REJECTED 是安全拒绝，FAILED 是系统故障。"""
    assert not _match("rejected", "FAILED"), "A-2: FAILED 被归入 rejected，污染安全拒绝语义"


def test_a3_failed_not_in_pending() -> None:
    """A-3: FAILED 是终态，不该出现在 pending。"""
    assert not _match("pending", "FAILED"), "A-3: FAILED 出现在 pending"


@pytest.mark.parametrize("state", sorted(s.value for s in TERMINAL_STATES))
def test_a4_all_terminal_states_visible_in_all(state: str) -> None:
    """A-4: status=all 必须含全部终态（含新增的 FAILED）。"""
    assert _match("all", state), f"A-4: {state} 在 status=all 中不可见"


def test_a5_existing_states_not_regressed() -> None:
    """A-5: 三个既有状态归类不回归。"""
    assert _match("pending", State.WAIT_APPROVAL.value)
    assert _match("approved", State.FINISHED.value)
    assert _match("rejected", State.REJECTED.value)
    assert not _match("approved", State.REJECTED.value)
    assert not _match("rejected", State.FINISHED.value)


def test_a6_every_terminal_state_has_explicit_home() -> None:
    """A-6: 每个终态都必须被显式归类，不能落进"兜底 return"。

    这条是本缺陷的根因守门：原实现末尾是 `return item.state == "REJECTED"`，
    任何新增终态都会静默落到这里并被判 False，三个列表全查不到。
    此后再加终态（如 CANCELLED），若不同步更新归类表，这条直接红。
    """
    from backend.app.api.routers.approvals import _classify_state

    for state in TERMINAL_STATES:
        bucket = _classify_state(state.value)
        assert bucket in {"pending", "approved", "rejected"}, (
            f"A-6: 终态 {state.value} 未被显式归类（得到 {bucket!r}）——"
            f"新增终态时必须同步更新 _classify_state 的归类表"
        )
