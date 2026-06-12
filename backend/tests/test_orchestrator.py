"""D3-b orchestrator 测试：分支驱动、逐点 emit/audit、哈希链、异常→error。

全部用 fake 协作者 + 注入 completion_fn 的真 LLMAdapter，不触网、不执行真命令。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from backend.app.agent.orchestrator import Orchestrator, most_restrictive
from backend.app.agent.state_machine import State
from backend.app.contracts.audit import GENESIS_HASH, AuditRecord, compute_curr_hash
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.stream import StreamEvent
from backend.app.contracts.tool import ToolSpec
from backend.app.contracts.untrusted import ToolResult
from backend.app.llm.adapter import LLMAdapter
from backend.app.mcp.gateway import CallOutcome, MCPGateway
from backend.app.mcp.registry import ToolRegistry

# ---- fakes ---------------------------------------------------------------

# 测试用工具：接受空 args（无 required、禁多余字段），供 gateway 三道闸放行。
_TEST_SPEC = ToolSpec(
    name="disk.usage",
    description="磁盘占用（测试用只读工具）",
    risk="R1",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    requires_roles=["operator"],
    reversible=True,
)


def _intent_json(*, need_observation: bool = False, tools: list[dict] | None = None) -> str:
    return json.dumps(
        {
            "intent": "clean_system_garbage",
            "confidence": 0.9,
            "need_observation": need_observation,
            "candidate_tools": tools if tools is not None else [{"name": "disk.usage", "args": {}}],
            "risk_hint": "medium",
            "justification": "test",
        }
    )


def _llm_returning(output: str) -> LLMAdapter:
    async def fn(messages):  # noqa: ANN001
        return output

    return LLMAdapter(completion_fn=fn)


def _llm_sequence(*outputs: str) -> LLMAdapter:
    """按调用次序返回不同输出的 LLM（用于 observe→re-plan 两阶段测试）。"""
    seq = list(outputs)
    calls = {"n": 0}

    async def fn(messages):  # noqa: ANN001
        out = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return out

    return LLMAdapter(completion_fn=fn)


class FakePolicy:
    def __init__(self, verdict: PolicyVerdict) -> None:
        self._verdict = verdict

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return self._verdict


class FakeExecutor:
    def __init__(self, *, exit_code: int = 0, raises: Exception | None = None) -> None:
        self.exit_code = exit_code
        self.raises = raises
        self.calls: list[CandidateTool] = []

    async def execute(self, tool: CandidateTool) -> ToolResult:
        self.calls.append(tool)
        if self.raises is not None:
            raise self.raises
        return ToolResult(
            tool=tool.name, args=tool.args, exit_code=self.exit_code, stdout_truncated="out"
        )


class FakeAudit:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


class FakeEvents:
    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    def emit(self, event: StreamEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type for e in self.events]


def _verdict(decision, *, role=None, risk="R1") -> PolicyVerdict:  # noqa: ANN001
    return PolicyVerdict(
        decision=decision,
        final_risk=risk,
        matched_rules=["rule.test"],
        reason="test",
        approval_required=(decision == "confirm"),
        approval_role=role,
    )


def _gateway(verdict: PolicyVerdict, executor: FakeExecutor) -> MCPGateway:
    return MCPGateway(ToolRegistry([_TEST_SPEC]), FakePolicy(verdict), executor)


def _build(llm, verdict, **exec_kw):  # noqa: ANN001
    audit, events = FakeAudit(), FakeEvents()
    executor = FakeExecutor(**exec_kw)
    orch = Orchestrator(
        llm=llm,
        gateway=_gateway(verdict, executor),
        audit=audit,
        events=events,
        trace_id="trace-test",
    )
    return orch, audit, events, executor


# ---- helpers -------------------------------------------------------------


def _assert_chain_intact(audit: FakeAudit) -> None:
    """逐条复算哈希链，验证连续且可复算。"""
    prev = GENESIS_HASH
    for i, rec in enumerate(audit.records):
        assert rec.seq == i
        assert rec.prev_hash == prev
        assert rec.curr_hash == compute_curr_hash(prev, rec.payload)
        prev = rec.curr_hash


# ---- tests ---------------------------------------------------------------


def test_most_restrictive_picks_deny() -> None:
    v = most_restrictive([_verdict("allow"), _verdict("confirm"), _verdict("deny")])
    assert v.decision == "deny"


def test_allow_runs_full_chain_to_finished() -> None:
    orch, audit, events, _ex = _build(_llm_returning(_intent_json()), _verdict("allow"))
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}], user_intent="clean"))
    assert end is State.FINISHED
    _assert_chain_intact(audit)
    # 逐点 emit 判定：RECEIVED/REJECTED/FINISHED 无独立前端事件
    assert "intent_parsed" in events.types()
    assert "plan_generated" in events.types()
    assert "policy_verdict" in events.types()
    assert "executing" in events.types()
    assert "tool_result" in events.types()
    assert "verified" in events.types()


def test_observation_branch_emits_observation() -> None:
    orch, _audit, events, ex = _build(
        _llm_returning(_intent_json(need_observation=True)), _verdict("allow")
    )
    asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert "observation" in events.types()
    # 观测经 gateway 调只读工具（allow），结果计入 observation 事件
    obs = [e for e in events.events if e.type == "observation"][0]
    assert len(obs.data["results"]) == 1
    assert obs.data["results"][0]["is_untrusted"] is True


def test_observation_skips_non_readonly_tools_defense_in_depth() -> None:
    """防御纵深：即便策略误放行变更工具(R3)，观测阶段也绝不执行它。

    观测仅跑只读(R0/R1)工具；变更工具留到 POLICY_CHECKED→执行路径。
    无此过滤时该工具会在观测阶段被执行一次（执行器被调两次）。
    """
    change_spec = ToolSpec(
        name="service.restart",
        description="重启服务（变更类）",
        risk="R3",
        input_schema={
            "type": "object",
            "properties": {"service_name": {"type": "string", "minLength": 1}},
            "required": ["service_name"],
            "additionalProperties": False,
        },
        requires_roles=["admin"],
        reversible=False,
    )
    intent = json.dumps(
        {
            "intent": "restart_svc",
            "confidence": 0.9,
            "need_observation": True,
            "candidate_tools": [{"name": "service.restart", "args": {"service_name": "nginx"}}],
            "risk_hint": "high",
            "justification": "test",
        }
    )
    audit, events = FakeAudit(), FakeEvents()
    executor = FakeExecutor()
    # 策略被误配为 allow（应为 confirm/deny）；防御纵深须挡住观测阶段执行
    gateway = MCPGateway(ToolRegistry([change_spec]), FakePolicy(_verdict("allow")), executor)
    orch = Orchestrator(llm=_llm_returning(intent), gateway=gateway, audit=audit, events=events)
    asyncio.run(orch.run([{"role": "user", "content": "x"}]))

    obs = [e for e in events.events if e.type == "observation"][0]
    assert obs.data["results"] == []  # 变更工具未在观测阶段执行
    # 执行器只在执行阶段被调一次（观测阶段被只读过滤挡下），而非两次
    assert len(executor.calls) == 1


def test_observe_then_replan_uses_second_plan_tools() -> None:
    """observe→re-plan 两阶段：观测用首次规划的只读工具，行动用二次规划的工具。

    首次 plan：need_observation=True，候选 disk.usage（只读观测）。
    二次 plan（回喂观测后）：need_observation=False，候选 disk.large_files（行动）。
    断言：观测执行了 disk.usage，行动执行了 disk.large_files（而非再次 disk.usage）。
    """
    first = json.dumps(
        {
            "intent": "inspect",
            "confidence": 0.9,
            "need_observation": True,
            "candidate_tools": [{"name": "disk.usage", "args": {}}],
            "risk_hint": "low",
            "justification": "先观测",
        }
    )
    second = json.dumps(
        {
            "intent": "act",
            "confidence": 0.9,
            "need_observation": False,
            "candidate_tools": [{"name": "disk.large_files", "args": {"path": "/var/log"}}],
            "risk_hint": "medium",
            "justification": "据观测行动",
        }
    )
    large_spec = ToolSpec(
        name="disk.large_files",
        description="大文件",
        risk="R1",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "pattern": "^/"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        requires_roles=["operator"],
        reversible=True,
    )
    audit, events = FakeAudit(), FakeEvents()
    executor = FakeExecutor()
    gateway = MCPGateway(
        ToolRegistry([_TEST_SPEC, large_spec]), FakePolicy(_verdict("allow")), executor
    )
    orch = Orchestrator(
        llm=_llm_sequence(first, second), gateway=gateway, audit=audit, events=events
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.FINISHED
    called = [c.name for c in executor.calls]
    assert called == ["disk.usage", "disk.large_files"]  # 观测→行动，无重复执行 disk.usage
    # plan_generated 事件反映的是二次规划的行动计划
    pg = [e for e in events.events if e.type == "plan_generated"][0]
    assert pg.data["candidate_tools"][0]["name"] == "disk.large_files"


def test_deny_goes_rejected_no_execution() -> None:
    orch, audit, events, ex = _build(_llm_returning(_intent_json()), _verdict("deny"))
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.REJECTED
    assert ex.calls == []
    assert "executing" not in events.types()
    # L-6 方案B：REJECTED 终态显式 emit rejected(cause=policy_deny)
    assert "rejected" in events.types()
    rej = [e for e in events.events if e.type == "rejected"][0]
    assert rej.data["cause"] == "policy_deny"
    _assert_chain_intact(audit)


def test_empty_candidates_denied() -> None:
    orch, _audit, _events, _ex = _build(_llm_returning(_intent_json(tools=[])), _verdict("allow"))
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.REJECTED  # 无候选合成 deny


def test_confirm_pauses_then_resume_approved() -> None:
    orch, audit, events, ex = _build(
        _llm_returning(_intent_json()), _verdict("confirm", role="admin")
    )
    paused = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert paused is State.WAIT_APPROVAL
    assert "await_approval" in events.types()
    end = asyncio.run(orch.resume(approved=True))
    assert end is State.FINISHED
    assert len(ex.calls) == 1  # 审批后经 gateway(approved=True) 执行
    _assert_chain_intact(audit)


def test_confirm_then_resume_rejected() -> None:
    orch, audit, events, ex = _build(
        _llm_returning(_intent_json()), _verdict("confirm", role="admin")
    )
    asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    end = asyncio.run(orch.resume(approved=False))
    assert end is State.REJECTED
    assert ex.calls == []
    # L-6 方案B：用户拒批 → 显式 emit rejected(cause=user_reject)
    assert "rejected" in events.types()
    rej = [e for e in events.events if e.type == "rejected"][0]
    assert rej.data["cause"] == "user_reject"
    _assert_chain_intact(audit)


def test_resume_outside_wait_approval_raises() -> None:
    orch, _audit, _events, _ex = _build(_llm_returning(_intent_json()), _verdict("allow"))
    with pytest.raises(RuntimeError):
        asyncio.run(orch.resume(approved=True))


def test_execution_failure_walks_full_chain_via_exit_code() -> None:
    """方案 B：执行失败(exit_code!=0)仍走 EXECUTED→VERIFIED→FINISHED，由 VERIFIED 判定。"""
    orch, audit, events, _ex = _build(
        _llm_returning(_intent_json()), _verdict("allow"), exit_code=1
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.FINISHED
    verified = [e for e in events.events if e.type == "verified"][0]
    assert "non-zero" in verified.data["summary"]
    _assert_chain_intact(audit)


def test_executor_exception_emits_error_and_stops() -> None:
    orch, _audit, events, _ex = _build(
        _llm_returning(_intent_json()), _verdict("allow"), raises=OSError("boom")
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.EXECUTING  # 停在执行态，未推进
    assert "error" in events.types()


def test_llm_network_error_emits_error_and_stops() -> None:
    async def fn(messages):  # noqa: ANN001
        raise httpx.ConnectError("no route")

    orch, _audit, events, _ex = _build(LLMAdapter(completion_fn=fn), _verdict("allow"))
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.RECEIVED  # 规划即失败，停在初态
    assert "error" in events.types()


def test_tool_result_forced_untrusted() -> None:
    """结果闸：即使 Executor 返回 is_untrusted=False，gateway 也强制改 True。"""

    class SneakyExecutor:
        async def execute(self, tool: CandidateTool) -> ToolResult:
            return ToolResult.model_construct(
                tool=tool.name,
                args={},
                exit_code=0,
                stdout_truncated="",
                is_untrusted=False,
                wrap_token="<<UNTRUSTED_TOOL_OUTPUT>>",
            )

    audit, events = FakeAudit(), FakeEvents()
    gateway = MCPGateway(
        ToolRegistry([_TEST_SPEC]), FakePolicy(_verdict("allow")), SneakyExecutor()
    )
    orch = Orchestrator(
        llm=_llm_returning(_intent_json()),
        gateway=gateway,
        audit=audit,
        events=events,
        trace_id="t",
    )
    asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    tr = [e for e in events.events if e.type == "tool_result"][0]
    assert tr.data["result"]["is_untrusted"] is True


def test_unregistered_tool_denied_by_gateway() -> None:
    """gateway 闸1：未注册工具 → orchestrator 拿到 deny → REJECTED，不执行。"""
    intent = _intent_json(tools=[{"name": "ghost.tool", "args": {}}])
    orch, _audit, events, ex = _build(_llm_returning(intent), _verdict("allow"))
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.REJECTED
    assert ex.calls == []


def test_bad_args_denied_by_gateway_schema_gate() -> None:
    """gateway 闸2：args 含未声明字段 → 结构校验失败 → deny → REJECTED。"""
    intent = _intent_json(tools=[{"name": "disk.usage", "args": {"shell": "rm -rf /"}}])
    orch, _audit, _events, ex = _build(_llm_returning(intent), _verdict("allow"))
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.REJECTED
    assert ex.calls == []


def test_audit_decision_key_only_holds_valid_decisions() -> None:
    """审计 payload 的 decision 键只能出现契约3 Decision 值，不被阶段语义污染。"""
    valid = {"allow", "deny", "confirm"}
    for verdict in (_verdict("allow"), _verdict("deny"), _verdict("confirm", role="admin")):
        _orch, audit, _events, _ex = _build(_llm_returning(_intent_json()), verdict)
        asyncio.run(_orch.run([{"role": "user", "content": "x"}]))
        if _orch.state is State.WAIT_APPROVAL:
            asyncio.run(_orch.resume(approved=True))
        for rec in audit.records:
            if "decision" in rec.payload:
                assert rec.payload["decision"] in valid


# ---- 多工具逐裁决逐执行（D12 重构核心）---------------------------------


class PerToolPolicy:
    """按工具名返回不同裁决，用于多工具混合裁决测试。"""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping  # tool name → decision

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        decision = self._mapping.get(tool.name, "allow")
        return PolicyVerdict(
            decision=decision,
            final_risk="R2" if decision != "allow" else "R0",
            matched_rules=[f"rule.{tool.name}"],
            reason=f"{tool.name}:{decision}",
            approval_required=(decision == "confirm"),
            approval_role="admin" if decision == "confirm" else None,
        )


# 两个测试工具规格，args 为空对象。
_SPEC_A = ToolSpec(
    name="tool.a",
    description="a",
    risk="R0",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    requires_roles=["operator"],
    reversible=True,
)
_SPEC_B = ToolSpec(
    name="tool.b",
    description="b",
    risk="R2",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    requires_roles=["operator"],
    reversible=True,
)


def _multi_intent() -> str:
    return json.dumps(
        {
            "intent": "multi",
            "confidence": 0.9,
            "need_observation": False,
            "candidate_tools": [
                {"name": "tool.a", "args": {}},
                {"name": "tool.b", "args": {}},
            ],
            "risk_hint": "medium",
            "justification": "multi tool",
        }
    )


def _multi_build(mapping: dict[str, str]):  # noqa: ANN201
    audit, events = FakeAudit(), FakeEvents()
    executor = FakeExecutor()
    gateway = MCPGateway(ToolRegistry([_SPEC_A, _SPEC_B]), PerToolPolicy(mapping), executor)
    orch = Orchestrator(
        llm=_llm_returning(_multi_intent()), gateway=gateway, audit=audit, events=events
    )
    return orch, audit, events, executor


def test_multi_all_allow_executes_all_in_order() -> None:
    orch, audit, events, ex = _multi_build({"tool.a": "allow", "tool.b": "allow"})
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.FINISHED
    assert [c.name for c in ex.calls] == ["tool.a", "tool.b"]
    # 每个工具各自 tool_result 留痕
    tr = [e for e in events.events if e.type == "tool_result"]
    assert {e.data["result"]["tool"] for e in tr} == {"tool.a", "tool.b"}
    _assert_chain_intact(audit)


def test_multi_allow_plus_deny_rejects_whole_plan() -> None:
    """原子计划：含 deny 工具 → 整批 REJECTED，allow 工具也不执行。"""
    orch, audit, _events, ex = _multi_build({"tool.a": "allow", "tool.b": "deny"})
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.REJECTED
    assert ex.calls == []  # 含禁止动作的计划不部分执行
    _assert_chain_intact(audit)


def test_multi_allow_plus_confirm_approval_matches_execution() -> None:
    """审批错配修复：面板列出 confirm 工具(tool.b)，批准后执行的是同一批(a+b)。"""
    orch, audit, events, ex = _multi_build({"tool.a": "allow", "tool.b": "confirm"})
    paused = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert paused is State.WAIT_APPROVAL
    # await_approval 列出的 confirm 工具确实是 tool.b
    aa = [e for e in events.events if e.type == "await_approval"][0]
    assert [t["tool"] for t in aa.data["tools"]] == ["tool.b"]
    # 批准 → 执行整批，且执行的就是面板涉及的同一批（a 先 b 后）
    end = asyncio.run(orch.resume(approved=True))
    assert end is State.FINISHED
    assert [c.name for c in ex.calls] == ["tool.a", "tool.b"]
    _assert_chain_intact(audit)


def test_multi_confirm_reject_executes_nothing() -> None:
    orch, _audit, _events, ex = _multi_build({"tool.a": "allow", "tool.b": "confirm"})
    asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    end = asyncio.run(orch.resume(approved=False))
    assert end is State.REJECTED
    assert ex.calls == []  # 拒绝审批 → 整批不执行


def test_multi_per_tool_verdicts_in_policy_event() -> None:
    """policy_verdict 事件携带逐工具裁决，前端可按工具粒度展示。"""
    orch, _audit, events, _ex = _multi_build({"tool.a": "allow", "tool.b": "confirm"})
    asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    pv = [e for e in events.events if e.type == "policy_verdict"][0]
    per = {d["tool"]: d["verdict"]["decision"] for d in pv.data["per_tool"]}
    assert per == {"tool.a": "allow", "tool.b": "confirm"}
    assert pv.data["verdict"]["decision"] == "confirm"  # 整批=最严


# ---- 批次中途失败（第二轮修订3）---------------------------------------


class _FailOnNthExecutor:
    """第 fail_on 次 execute 调用时抛 OSError（错误信息含工具名）。"""

    def __init__(self, fail_on: int) -> None:
        self.fail_on = fail_on
        self.calls: list[CandidateTool] = []

    async def execute(self, tool: CandidateTool) -> ToolResult:
        self.calls.append(tool)
        if len(self.calls) == self.fail_on:
            raise OSError(f"boom on {tool.name}")
        return ToolResult(tool=tool.name, args=tool.args, exit_code=0, stdout_truncated="out")


def test_batch_mid_failure_via_executor_exception() -> None:
    """批次 [tool.a, tool.b] 均 allow，执行第 2 个时执行器抛异常 → 停在 EXECUTING、emit error。"""
    audit, events = FakeAudit(), FakeEvents()
    executor = _FailOnNthExecutor(fail_on=2)
    gateway = MCPGateway(
        ToolRegistry([_SPEC_A, _SPEC_B]),
        PerToolPolicy({"tool.a": "allow", "tool.b": "allow"}),
        executor,
    )
    orch = Orchestrator(
        llm=_llm_returning(_multi_intent()), gateway=gateway, audit=audit, events=events
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))

    assert end is State.EXECUTING  # 未推进到 FINISHED
    # 仅 tool.a 产出 tool_result
    tr = [e for e in events.events if e.type == "tool_result"]
    assert len(tr) == 1
    assert tr[0].data["result"]["tool"] == "tool.a"
    # 末尾事件为 error，且携带具体失败工具名
    assert events.types()[-1] == "error"
    err = [e for e in events.events if e.type == "error"][-1]
    assert "tool.b" in err.data["message"]
    # 审计：tool.a 的 exit_code 已留痕，但未出现 VERIFIED 阶段
    assert any(r.payload.get("tool") == "tool.a" for r in audit.records)
    assert all(r.phase != State.VERIFIED.value for r in audit.records)


class _SecondBlockedGateway:
    """fake gateway：evaluate 全 allow；call 对 tool.b 返回 executed=False（二次过闸拦下）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_read_only(self, tool: CandidateTool) -> bool:
        return True

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return PolicyVerdict(
            decision="allow",
            final_risk="R0",
            matched_rules=[],
            reason="ok",
            approval_required=False,
        )

    async def call(self, tool: CandidateTool, *, approved: bool = False) -> CallOutcome:
        self.calls.append(tool.name)
        if tool.name == "tool.b":
            return CallOutcome(
                executed=False,
                verdict=self.evaluate(tool),
                reason="blocked by defense-in-depth second pass",
            )
        return CallOutcome(
            executed=True,
            result=ToolResult(tool=tool.name, args={}, exit_code=0, stdout_truncated="ok"),
            verdict=self.evaluate(tool),
        )


def test_batch_mid_blocked_by_gateway_second_pass() -> None:
    """批次第 2 个工具在 gateway 二次过闸被拦（executed=False）→ 停在 EXECUTING、emit error。"""
    audit, events = FakeAudit(), FakeEvents()
    gateway = _SecondBlockedGateway()
    orch = Orchestrator(
        llm=_llm_returning(_multi_intent()),
        gateway=gateway,  # type: ignore[arg-type]
        audit=audit,
        events=events,
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))

    assert end is State.EXECUTING
    # tool.a 已执行（产出 tool_result），tool.b 被拦
    tr = [e for e in events.events if e.type == "tool_result"]
    assert len(tr) == 1
    assert tr[0].data["result"]["tool"] == "tool.a"
    assert gateway.calls == ["tool.a", "tool.b"]  # 两个都尝试，tool.b 被拦
    assert events.types()[-1] == "error"
    err = [e for e in events.events if e.type == "error"][-1]
    assert "tool.b" in err.data["message"]
    assert all(r.phase != State.VERIFIED.value for r in audit.records)


# ---- L2: 有界多轮 observe→re-plan 终止条件 -------------------------------

# 两个只读工具规格供多轮观测使用。
_OBS_USAGE = ToolSpec(
    name="disk.usage",
    description="磁盘占用",
    risk="R1",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    requires_roles=["operator"],
    reversible=True,
)
_OBS_LARGE = ToolSpec(
    name="disk.large_files",
    description="大文件",
    risk="R1",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "pattern": "^/"}},
        "required": ["path"],
        "additionalProperties": False,
    },
    requires_roles=["operator"],
    reversible=True,
)


def _obs_plan(*, need_observation: bool, tools: list[dict]) -> str:
    return json.dumps(
        {
            "intent": "multi_observe",
            "confidence": 0.9,
            "need_observation": need_observation,
            "candidate_tools": tools,
            "risk_hint": "low",
            "justification": "test",
        }
    )


def _obs_gateway(executor: FakeExecutor) -> MCPGateway:
    return MCPGateway(
        ToolRegistry([_OBS_USAGE, _OBS_LARGE]), FakePolicy(_verdict("allow")), executor
    )


def test_two_round_observation_then_converge() -> None:
    """两轮观测后收敛：round0 观测 disk.usage→换计划，round1 观测 disk.large_files→
    二次规划 need_observation=False 收敛，进入行动规划并执行。共 2 个 observation 事件。"""
    p0 = _obs_plan(need_observation=True, tools=[{"name": "disk.usage", "args": {}}])
    p1 = _obs_plan(
        need_observation=True, tools=[{"name": "disk.large_files", "args": {"path": "/var/log"}}]
    )
    p2 = _obs_plan(need_observation=False, tools=[{"name": "disk.usage", "args": {}}])
    audit, events = FakeAudit(), FakeEvents()
    executor = FakeExecutor()
    orch = Orchestrator(
        llm=_llm_sequence(p0, p1, p2),
        gateway=_obs_gateway(executor),
        audit=audit,
        events=events,
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.FINISHED
    obs = [e for e in events.events if e.type == "observation"]
    assert len(obs) == 2  # 两轮观测
    assert len(obs[0].data["results"]) == 1  # round0 观测 disk.usage
    assert len(obs[1].data["results"]) == 1  # round1 观测 disk.large_files
    _assert_chain_intact(audit)


def test_observation_round_limit_forces_planning() -> None:
    """达上限强制进入规划：planner 每轮都 need_observation=True 且候选各异（不自然收敛），
    应在 max_observation_rounds 轮后被截断，进入规划并执行。"""
    calls = {"n": 0}

    async def fn(messages):  # noqa: ANN001
        n = calls["n"]
        calls["n"] += 1
        # 每轮候选 path 各异 → 指纹不同 → 不触发"无推进"截断，只能靠轮次上限收口
        return _obs_plan(
            need_observation=True,
            tools=[{"name": "disk.large_files", "args": {"path": f"/var/log/{n}"}}],
        )

    audit, events = FakeAudit(), FakeEvents()
    executor = FakeExecutor()
    orch = Orchestrator(
        llm=LLMAdapter(completion_fn=fn),
        gateway=_obs_gateway(executor),
        audit=audit,
        events=events,
        max_observation_rounds=2,
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    # 达上限退出循环后仍进入规划→执行（最后一轮计划的 disk.large_files）
    assert end is State.FINISHED
    obs = [e for e in events.events if e.type == "observation"]
    assert len(obs) == 2  # 恰好 max_observation_rounds 轮，未无限观测
    _assert_chain_intact(audit)


def test_infinite_loop_truncated_by_identical_candidates() -> None:
    """无限循环被截断：planner 反复返回同一 need_observation=True 计划，
    候选与上轮一致 → 第一轮后即截断，仅 1 个 observation 事件（防死循环）。"""
    same = _obs_plan(need_observation=True, tools=[{"name": "disk.usage", "args": {}}])
    audit, events = FakeAudit(), FakeEvents()
    executor = FakeExecutor()
    orch = Orchestrator(
        llm=_llm_returning(same),
        gateway=_obs_gateway(executor),
        audit=audit,
        events=events,
        max_observation_rounds=5,
    )
    end = asyncio.run(orch.run([{"role": "user", "content": "x"}]))
    assert end is State.FINISHED
    obs = [e for e in events.events if e.type == "observation"]
    assert len(obs) == 1  # 候选无推进 → 截断，未跑满 5 轮
    _assert_chain_intact(audit)
