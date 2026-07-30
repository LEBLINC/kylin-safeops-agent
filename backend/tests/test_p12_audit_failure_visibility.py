"""P1-2 补做：审计写入失败必须留痕；锁覆盖面须含 SoD 等外部调用方。

锁解决的是"为什么丢"（并发下链分叉），不解决"丢了没人知道"——
approvals.py 的 SoD 违规审计原本是 `except Exception: pass`，吞掉的是
一条"自批自"的安全事件，静默失败等于该事件从未发生。S8 要求"审计失败
不杀安全决策"，不要求不记录。

  L-1 SoD 审计落库失败时留 ERROR 日志且带 traceback（不再静默），
      且拒批仍然生效——S8 不变量与留痕要求在同一条端到端用例里一起验
  L-3 _audit_lock 覆盖外部调用方：approvals 走的是同一 orchestrator 实例的
      同一把锁，与 orchestrator 内部调用互斥（决定 SoD 审计是否需另行挪位）
"""

from __future__ import annotations

import asyncio
import logging

from backend.app.agent.orchestrator import Orchestrator
from backend.app.api.app import get_gateway
from backend.app.audit import write_executor as we
from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.stream import StreamEvent


class _ExplodingSink:
    """落库必炸——模拟审计库不可写（磁盘满 / 权限 / 锁死）。"""

    def append(self, record: AuditRecord) -> None:
        raise OSError("audit db is read-only")


class _CollectingSink:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


class _NullEvents:
    def emit(self, event: StreamEvent) -> None:
        pass


def _orch(sink) -> Orchestrator:  # noqa: ANN001
    return Orchestrator(
        llm=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
        audit=sink,
        events=_NullEvents(),
    )


def _r2_confirm_gateway():  # noqa: ANN202
    """裁决 confirm 且 approval_role=operator 的 gateway。

    必须是 operator 可批的等级：R3 会被 approvals 的 RBAC 闸先拦成 403，
    根本走不到 SoD 分支——那样 L-1 会因为"403 来对了但来自别处"而假绿。
    admin 又会命中 _admin_bypass_sod 旁路，同样到不了。故取 R2 + operator。
    """
    from backend.app.contracts.intent import CandidateTool
    from backend.app.contracts.policy import PolicyVerdict
    from backend.app.contracts.tool import ToolSpec
    from backend.app.contracts.untrusted import ToolResult
    from backend.app.mcp.gateway import MCPGateway
    from backend.app.mcp.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="service.restart",
            description="重启服务",
            risk="R2",
            input_schema={"type": "object", "properties": {}, "additionalProperties": True},
            requires_roles=["operator"],
            reversible=True,
        )
    )

    class _Policy:
        def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
            return PolicyVerdict(
                decision="confirm",
                final_risk="R2",
                matched_rules=["fake:confirm"],
                reason="needs approval",
                approval_required=True,
                approval_role="operator",
            )

    class _Executor:
        async def execute(self, tool: CandidateTool) -> ToolResult:
            return ToolResult(tool=tool.name, args=tool.args, exit_code=0, stdout_truncated="ok")

    return MCPGateway(registry, _Policy(), _Executor())


def test_l1_sod_audit_failure_is_logged_with_traceback() -> None:
    """L-1: SoD 审计落库失败必须留 ERROR + traceback，不能静默吞掉。

    必须打真端点：在测试里自己写一遍 log.exception 只能证明"我会写"，
    证明不了 approvals.py 那段 except 改对了。这里把 orchestrator 的 sink
    换成必炸的，再走真实的自批自流程，让那段 except 真正被执行到。

    不用 caplog：lifespan 会调 dictConfig 重装 root handler，把 caplog 的
    handler 顶掉，导致日志明明打了却捕不到（假红）。改为直接在目标 logger
    上挂一个收集 handler，不受 root 重配影响。

    L-2（S8：审计失败不改变安全决策）由本用例的 403 断言一并承载。
    """
    import os

    import httpx

    from backend.app.api import app as app_module
    from backend.app.api.app import create_app, lifespan

    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_gateway] = _r2_confirm_gateway
        async with lifespan(app):
            registry = app_module.get_registry()
            transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/chat", json={"message": "重启服务"})
                trace_id = resp.json()["trace_id"]

                loop = asyncio.get_running_loop()
                deadline = loop.time() + 5.0
                while loop.time() < deadline:
                    s = registry.get(trace_id)
                    if s is not None and s.orchestrator.state.value == "WAIT_APPROVAL":
                        break
                    await asyncio.sleep(0.01)

                session = registry.get(trace_id)
                assert session is not None, "L-1 前提：会话不存在"
                assert (
                    session.orchestrator.state.value == "WAIT_APPROVAL"
                ), f"L-1 前提：应停在 WAIT_APPROVAL，实际 {session.orchestrator.state.value}"
                # dev 模式下 principal.user 恒为 "dev"，故 actor 与 approver 同名 → 命中 SoD
                session.orchestrator.set_actor("dev", frozenset({"operator"}))
                # 让 SoD 审计落库必炸
                session.orchestrator._audit = _ExplodingSink()  # type: ignore[attr-defined]

                rr = await client.post(
                    "/api/approvals/resume",
                    headers={"X-User-Role": "operator"},
                    json={"trace_id": trace_id, "approved": True},
                )
                assert rr.status_code == 403, f"L-1 前提：应命中 SoD 403，实际 {rr.status_code}"
                assert "SoD" in rr.json().get(
                    "detail", ""
                ), f"L-1 前提：403 必须来自 SoD 而非 RBAC 闸，实际 {rr.json().get('detail')}"

    target = logging.getLogger("backend.app.api.routers.approvals")
    handler = _Capture(level=logging.ERROR)
    target.addHandler(handler)
    old_mode = os.environ.get("KYLIN_AUTH_MODE")
    os.environ["KYLIN_AUTH_MODE"] = "dev"
    try:
        asyncio.run(scenario())
    finally:
        target.removeHandler(handler)
        if old_mode is None:
            os.environ.pop("KYLIN_AUTH_MODE", None)
        else:
            os.environ["KYLIN_AUTH_MODE"] = old_mode

    sod_errors = [r for r in captured if "SoD" in r.getMessage()]
    assert sod_errors, (
        "L-1: SoD 审计落库失败未产生 ERROR 日志——安全事件被静默吞掉。"
        f"实际捕获：{[r.getMessage() for r in captured]}"
    )
    assert (
        sod_errors[0].exc_info is not None
    ), "L-1: 日志缺 traceback（用了 warning 而非 exception）"


def test_l3_audit_lock_covers_external_callers() -> None:
    """L-3: 外部调用方（approvals SoD 路径）与内部调用共用同一把锁。

    approvals.py 调的是 session.orchestrator._append_audit——同一实例、
    同一把 self._audit_lock。故并发混合两类调用时链仍不分叉。
    这条决定 SoD 审计是否还需要挪到 begin_resume 之后：若锁已覆盖，不需要。
    """
    orch = _orch(sink := _CollectingSink())

    async def _external() -> None:
        """模拟 approvals 从请求协程里打的那条 SoD 审计。"""
        await orch._append_audit({"cause": "sod_violation"})

    async def _drive() -> None:
        we.start_executor()
        try:
            await asyncio.gather(
                *(orch._append_audit({"i": i}) for i in range(10)),
                *(_external() for _ in range(10)),
            )
        finally:
            we.shutdown_executor()

    asyncio.run(_drive())

    seqs = [r.seq for r in sink.records]
    assert len(seqs) == 20, f"L-3: 应落库 20 条，实际 {len(seqs)}"
    assert len(set(seqs)) == 20, f"L-3: seq 重复——外部调用方未被同一把锁覆盖：{sorted(seqs)}"
