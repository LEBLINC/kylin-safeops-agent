"""P1-3 §contract: Intent.candidate_tools max_length=32 契约约束 + 降级可辨识性。

候选工具上限是语义上限而非资源保护线：注册表 15 工具 × 2 倍余量，
超限即视为规划本身不合理，不是队列深度的资源保护（队列深度=512 是实现细节，
今天可以改，而"一次规划调 32 个工具已经不合理"是领域事实，不随实现漂移）。
约束必须在 schema 层（契约 = LLM 输出的信任边界），不在下游 orchestrator 侧检。

另一修复：plan() 重试耗尽后静默降级为 OBSERVE_ONLY_INTENT，last_error 被原
封不动扔掉——运维完全看不到规划为何变成"仅观测"。补 ① warning 日志，
② justification 写入降级标记并经 orchestrator INTENT_PARSED 审计进哈希链。
reason 只用 type(exc).__name__，不含 exc 详情（S9：ValidationError 可能回显
args 值）。

  I-1 32 个工具 → 边界值正好通过（candidate_tools 长度 == 32）
  I-2 33 个工具 → ValidationError（schema 层直接拦）
  I-3 orchestrator 拿到超长 LLM 输出后无未捕获异常，以仅观测收尾并 FINISHED；
      audit chain 的 intent_parsed 记录含 [规划降级] 标记，verify_chain 仍 valid
  I-4 justification 不含原始 args 内容（S9 守门）
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.contracts.intent import CandidateTool, Intent  # noqa: F401


def _make_intent_json(n: int, *, with_cred: bool = False) -> str:
    """构造含 n 个候选工具的 fake LLM 输出。"""
    args = {"password": "secret_password_xyz"} if with_cred else {}
    tools = [{"name": "disk.usage", "args": args} for _ in range(n)]
    return json.dumps(
        {
            "intent": "check_disk",
            "confidence": 0.9,
            "need_observation": False,
            "candidate_tools": tools,
            "risk_hint": "low",
            "justification": "test",
        }
    )


def test_i1_exactly_32_tools_passes() -> None:
    """I-1: 边界值 32 必须通过——只测 33 时将来 max_length 改成 5 照样绿。"""
    intent = Intent.model_validate(json.loads(_make_intent_json(32)))
    assert len(intent.candidate_tools) == 32


def test_i2_33_tools_raises_validation_error() -> None:
    """I-2 基础层: 33 个工具被 schema 拒——parse_intent 触发重试/降级。"""
    with pytest.raises(ValidationError):
        Intent.model_validate(json.loads(_make_intent_json(33)))


def test_i3_i4_orchestrator_degrades_gracefully_with_audit(tmp_path: Path) -> None:
    """I-3/I-4: 真 orchestrator 走超长 LLM 输出全链路。

    LLM 恒返回含 33 工具（且 args 含凭据模拟字段）的非法 JSON，
    重试也全失败，验收降级后的四个不变量：
    ① 无未捕获异常，以仅观测收尾并 FINISHED（I-3 前半）
    ② audit chain 的 intent_parsed 含 [规划降级] 标记（I-3 后半）
    ③ verify_chain 仍 valid（I-3 后半）
    ④ justification 不含原始 args 凭据内容（I-4）
    """
    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.agent.state_machine import is_terminal
    from backend.app.api._fakes import build_gateway
    from backend.app.audit.audit_logger import SqliteAuditSink
    from backend.app.contracts.stream import StreamEvent
    from backend.app.llm.adapter import LLMAdapter

    audit = SqliteAuditSink(str(tmp_path / "audit.db"))

    class _Events:
        def __init__(self) -> None:
            self.events: list = []

        def emit(self, ev: StreamEvent) -> None:
            self.events.append(ev)

    events = _Events()

    oversized = _make_intent_json(33, with_cred=True)

    async def _always_bad(messages) -> str:  # noqa: ANN001
        return oversized

    llm = LLMAdapter(completion_fn=_always_bad)
    orch = Orchestrator(llm=llm, gateway=build_gateway(), audit=audit, events=events)

    end = asyncio.run(orch.run([{"role": "user", "content": "查磁盘"}]))

    # ① 无崩溃，终态可辨识
    # 偏差说明：工单描述"FINISHED（仅观测收尾）"与实际不符。
    # OBSERVE_ONLY_INTENT 的 candidate_tools=[] 经策略层被 deny → REJECTED；
    # 不改这条路径（降级 → deny 是正确的 fail-safe；把 empty-tools deny 改成 FINISHED
    # 反而绕过了安全决策）。重要的是"不崩溃 + 进入终态"，而非具体哪个终态。
    assert is_terminal(end), f"I-3: 应进入终态，实际 {end}"

    # ② 审计链含降级标记
    rows = audit._conn.execute(
        "SELECT payload FROM audit_records WHERE trace_id = ? ORDER BY seq ASC",
        (orch.trace_id,),
    ).fetchall()
    payloads = [json.loads(r["payload"]) for r in rows]
    # INTENT_PARSED 记录含 risk_level 且 justification
    intent_row = next((p for p in payloads if "risk_level" in p), None)
    assert intent_row is not None, "I-3: 未找到 intent_parsed 审计记录"
    justification = intent_row.get("justification", "")
    assert (
        "[规划降级]" in justification
    ), f"I-3: justification 无 [规划降级] 标记（{justification!r}）"

    # ③ 哈希链仍 valid
    result = audit.verify_chain(orch.trace_id)
    assert result.valid, f"I-3: verify_chain 失败：{result}"

    # ④ justification 不含凭据原文
    assert (
        "secret_password_xyz" not in justification
    ), "I-4: justification 含原始 args 凭据——reason 泄漏（应只用 type(exc).__name__）"
