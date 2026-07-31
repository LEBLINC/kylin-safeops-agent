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


def test_contract_value_domains_frozen() -> None:
    """6 份契约的值域冻结守门（之七十五 H-6 contracts 窄例外的防回归闸）。

    H-6 曾获授权改 contracts/ 的 docstring 散文（去协作者代号）。授权边界是
    "只改散文、契约语义零变更"——本用例把该边界钉成可执行断言：任何一次改动
    只要碰到值域/常量/hash 口径就会红。

    GENESIS_HASH 与 compute_curr_hash 的期望值是**字节级**写死的：S3 哈希链
    一旦口径漂移，已落库的历史审计链会整条失效且无法追溯，故此处不容许"重算
    期望值让测试变绿"——期望值变了就是事故。
    """
    from typing import get_args

    from backend.app.contracts.policy import Decision
    from backend.app.contracts.stream import EventType
    from backend.app.contracts.tool import RiskLevel

    # 契约6 EventType：13 值（新增终态信号须复用既有 error，不得扩这个枚举）
    assert len(get_args(EventType)) == 13

    # 契约3 Decision：三态，不多不少（shield 的 warn 归并入 allow）
    assert sorted(get_args(Decision)) == ["allow", "confirm", "deny"]

    # 契约1 RiskLevel：R0-R4
    assert sorted(get_args(RiskLevel)) == ["R0", "R1", "R2", "R3", "R4"]

    # 契约5 哈希链口径：创世值 + 复算结果均字节级冻结
    assert GENESIS_HASH == "0" * 64
    assert (
        compute_curr_hash(GENESIS_HASH, {"a": 1})
        == "fc6cee09194dd2578bd7664604fcb72a539066fd34544cea0009c43eb6cdc289"
    )

    # 契约4 不可信定界符
    assert UNTRUSTED_WRAP_TOKEN == "<<UNTRUSTED_TOOL_OUTPUT>>"

    # 契约2 candidate_tools 上限（P1-3）：语义上限而非资源上限。
    # 取值依据是"注册表 15 工具 × 2 倍余量"，不是队列深度反推——后者是
    # 实现细节（今天 512、明天可能改），前者是领域事实。新约束自身也须被
    # 守住：有人调大到 512 时这条会红。
    from backend.app.contracts.intent import Intent

    assert Intent.model_fields["candidate_tools"].metadata[0].max_length == 32
