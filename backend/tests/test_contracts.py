"""D2-a 契约层最小测试：构造合法实例、验证字段约束与哈希链可复算。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.contracts import (
    GENESIS_HASH,
    UNTRUSTED_WRAP_TOKEN,
    AuditRecord,
    CandidateTool,
    Intent,
    PolicyVerdict,
    StreamEvent,
    ToolResult,
    ToolSpec,
    canonical_json,
    compute_curr_hash,
)


def test_tool_spec_minimal() -> None:
    spec = ToolSpec(
        name="disk.large_files",
        description="列出大文件",
        risk="R1",
        input_schema={"type": "object"},
        requires_roles=["operator"],
        reversible=True,
    )
    assert spec.risk == "R1"


def test_tool_spec_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ToolSpec(
            name="x",
            description="d",
            risk="R0",
            input_schema={},
            requires_roles=[],
            reversible=True,
            shell="rm -rf /",  # type: ignore[call-arg]
        )


def test_intent_confidence_bounds() -> None:
    intent = Intent(
        intent="clean_system_garbage",
        confidence=0.86,
        need_observation=True,
        candidate_tools=[CandidateTool(name="disk.large_files", args={"path": "/var/log"})],
        risk_hint="medium",
        justification="根分区占用高",
    )
    assert intent.candidate_tools[0].name == "disk.large_files"
    with pytest.raises(ValidationError):
        Intent(
            intent="x",
            confidence=1.5,
            need_observation=False,
            risk_hint="low",
            justification="j",
        )


def test_policy_verdict_optionals_default_none() -> None:
    verdict = PolicyVerdict(
        decision="confirm",
        final_risk="R3",
        reason="高危操作",
        approval_required=True,
        approval_role="admin",
    )
    assert verdict.matched_rules == []
    assert verdict.safer_alternative is None


def test_tool_result_defaults_untrusted() -> None:
    result = ToolResult(tool="disk.large_files", exit_code=0, stdout_truncated="...")
    assert result.is_untrusted is True
    assert result.wrap_token == UNTRUSTED_WRAP_TOKEN


def test_canonical_json_is_stable() -> None:
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b == '{"a":2,"b":1}'


def test_hash_chain_recomputable_and_tamper_evident() -> None:
    payload0 = {"user_intent": "clean", "risk_level": "R1"}
    h0 = compute_curr_hash(GENESIS_HASH, payload0)
    rec0 = AuditRecord(
        trace_id="t1",
        seq=0,
        phase="INTENT_PARSED",
        payload=payload0,
        prev_hash=GENESIS_HASH,
        curr_hash=h0,
    )
    payload1 = {"decision": "allow"}
    h1 = compute_curr_hash(rec0.curr_hash, payload1)
    # 复算一致
    assert compute_curr_hash(GENESIS_HASH, payload0) == rec0.curr_hash
    # 篡改 payload0 后，后续链值对不上
    tampered = compute_curr_hash(GENESIS_HASH, {"user_intent": "HACKED", "risk_level": "R1"})
    assert tampered != rec0.curr_hash
    assert compute_curr_hash(tampered, payload1) != h1


def test_stream_event_rejects_bad_type() -> None:
    StreamEvent(trace_id="t1", type="intent_parsed", ts=1.0, data={})
    with pytest.raises(ValidationError):
        StreamEvent(trace_id="t1", type="bogus", ts=1.0)  # type: ignore[arg-type]
