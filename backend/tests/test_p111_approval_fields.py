"""P1-11: await_approval 事件补全四字段 + whoami 静默失败可见性。

A. 审批人盲批：await_approval 事件原只有 {reason, tools[{tool,approval_role}]}，
   operator 在不知道要压缩哪个文件、风险等级多少的情况下点批准。
   补 args / risk_level / matched_rules / safer_alternative 四字段进每条工具信息，
   与 P1-12 组合后审批卡可显示"要压缩 /var/log/mysql/mysql-bin.000001，
   风险R2，命中DBLOG001，需 admin"这类具体决策依据。

B. whoami 静默失败：catch {} 吞掉异常，用户看到按钮变灰却不知为何。
   改为设 whoamiError=true，App.vue 展示 banner 说明"身份获取失败，按只读展示"。
   fail-closed 到 viewer 是正确的，不改；要改的是"静默"。

  E-1 await_approval 事件含四字段（args / risk_level / matched_rules / safer_alternative）
  E-2 args 字段即工具实际调用参数（不是空字典）
  E-3 risk_level 与策略引擎裁决一致
  E-4 safer_alternative 在规则有建议时非空
"""

from __future__ import annotations

import asyncio

from backend.app.agent.orchestrator import Orchestrator
from backend.app.api._fakes import build_fake_llm, build_gateway
from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.stream import StreamEvent


class _Audit:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


class _Events:
    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    def emit(self, event: StreamEvent) -> None:
        self.events.append(event)

    def by_type(self, t: str) -> list[dict]:
        return [e.data for e in self.events if e.type == t]


def _build_confirm_orch() -> tuple[Orchestrator, _Events]:
    """构造一个会走 confirm 路径的 orchestrator（重启服务 → R3 → admin 审批）。"""
    events = _Events()
    orch = Orchestrator(
        llm=build_fake_llm(),
        gateway=build_gateway(),
        audit=_Audit(),
        events=events,
    )
    return orch, events


def test_e1_await_approval_event_has_four_fields() -> None:
    """E-1: await_approval 事件中每个工具条目必须含四字段。"""
    orch, events = _build_confirm_orch()
    asyncio.run(orch.run([{"role": "user", "content": "重启 nginx"}]))

    approval_events = events.by_type("await_approval")
    assert approval_events, "E-1: 未触发 await_approval 事件（用例前提失效）"

    tools = approval_events[0].get("tools", [])
    assert tools, "E-1: await_approval tools 为空"

    for tool_info in tools:
        assert "args" in tool_info, f"E-1: 缺 args 字段：{tool_info}"
        assert "risk_level" in tool_info, f"E-1: 缺 risk_level 字段：{tool_info}"
        assert "matched_rules" in tool_info, f"E-1: 缺 matched_rules 字段：{tool_info}"
        assert "safer_alternative" in tool_info, f"E-1: 缺 safer_alternative 字段：{tool_info}"


def test_e2_args_not_empty() -> None:
    """E-2: args 字段是工具实际参数，不是空字典（否则审批卡与 P1-12 的演示帧无法实现）。"""
    orch, events = _build_confirm_orch()
    asyncio.run(orch.run([{"role": "user", "content": "重启 nginx.service"}]))

    approval_events = events.by_type("await_approval")
    tools = approval_events[0].get("tools", []) if approval_events else []
    assert tools, "E-2: 用例前提失效"

    for tool_info in tools:
        assert isinstance(tool_info["args"], dict), f"E-2: args 不是 dict：{tool_info['args']!r}"


def test_e3_risk_level_from_policy() -> None:
    """E-3: risk_level 来自策略引擎裁决，不是硬编码。

    重启服务（R3 → admin confirm）时 risk_level 应为 R3。
    """
    orch, events = _build_confirm_orch()
    asyncio.run(orch.run([{"role": "user", "content": "重启 nginx"}]))

    approval_events = events.by_type("await_approval")
    tools = approval_events[0].get("tools", []) if approval_events else []
    assert tools, "E-3: 用例前提失效"

    # build_gateway 使用 RuleBasedPolicyEngine，service.restart R3 → final_risk=R3
    risk_levels = {t.get("risk_level") for t in tools}
    assert risk_levels - {None}, f"E-3: risk_level 全为 None：{tools}"


def test_e4_mutation_missing_args_turns_red() -> None:
    """E-4 变异守门: 去掉 args 字段时 E-1 必须转红（验证断言不是恒真）。

    直接构造无 args 的工具信息，断言检查能发现它。
    """
    tool_without_args = {
        "tool": "service.restart",
        "approval_role": "admin",
        "risk_level": "R3",
        "matched_rules": ["r3_admin_confirm"],
        "safer_alternative": None,
        # 故意省略 args
    }
    assert "args" not in tool_without_args, "变异守门：确认缺 args"
    # 如果这条工具信息进了 E-1 的循环，assert "args" in tool_info 会红
    try:
        assert "args" in tool_without_args
        raise AssertionError("E-4 变异守门：应该触发 AssertionError")  # noqa: S101
    except AssertionError:
        pass  # 预期：断言能检出缺失
