"""任务乙 — Executor 切真验证（FakeExecutor → PrivilegeExecutor）+ config.diff 处置。

覆盖：
1. 切真后主链路 smoke：chat(system.info) → FINISHED，有 tool_result，result.is_untrusted=True
   + 标准 wrap_token（结果闸密封真命令输出）。win32 下命令可能 127，断言聚焦方案B 语义与密封。
2. config.diff 已接回 + mcp 层聚合：intent 提议 config.diff → 已注册、经三道闸聚合（不再 gate1
   降级 REJECTED）；产 tool_result（决策⑤，详见 test_config_diff_aggregation）。
3. config.diff 已回到 /api/tools/registry（摘除恢复）。

注：app 默认 build_gateway 装配真 PrivilegeExecutor；win32 真命令多 127（方案B 正常 return），
真数据靠 CI ubuntu。本套件验证"接线正确 + 方案B 语义 + 结果闸密封 + config.diff 接回聚合"。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from backend.app.api._fakes import build_fake_llm
from backend.app.api.app import create_app, get_llm, lifespan
from backend.app.contracts.untrusted import UNTRUSTED_WRAP_TOKEN


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _consume_sse(client: httpx.AsyncClient, url: str) -> list[tuple[str, dict]]:
    """消费 SSE 到 done，返回 [(event_type, data_dict), ...]。

    普通事件序列化为 `data: {StreamEvent json}\\n\\n`（type 在 JSON 内）；
    done 哨兵为 `event: done\\ndata: {}\\n\\n`。
    """
    events: list[tuple[str, dict]] = []
    async with client.stream("GET", url) as r:
        async for line in r.aiter_lines():
            if "event: done" in line:
                break
            if line.startswith("data: "):
                raw = line[len("data: ") :]
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and "type" in obj:
                    events.append((obj["type"], obj.get("data", {})))
    return events


# ---- 1. 切真后主链路 smoke ------------------------------------------------


def test_chat_smoke_real_executor_sealed() -> None:
    """chat(system.info) 经真 PrivilegeExecutor → FINISHED + tool_result 被结果闸密封。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                resp = await client.post("/api/chat", json={"message": "看下系统"})
                assert resp.status_code == 200
                events = await _consume_sse(client, resp.json()["stream_url"])

                types = [t for t, _ in events]
                assert "verified" in types
                tool_results = [d for t, d in events if t == "tool_result"]
                assert tool_results, "应有 tool_result 事件（真执行器产结果）"
                result = tool_results[0]["result"]
                # 结果闸密封真命令输出（不强求 exit_code==0：win32 命令可能 127）
                assert result["is_untrusted"] is True
                assert result["wrap_token"] == UNTRUSTED_WRAP_TOKEN

    asyncio.run(scenario())


# ---- 2. config.diff 接回 + mcp 层聚合 -------------------------------------


def test_config_diff_intent_aggregated_not_degraded() -> None:
    """intent 提议 config.diff → 已注册、经三道闸 + mcp 层聚合（不再 gate1 降级 REJECTED）。

    决策⑤：config.diff 经 gateway 聚合复用 config.hash_snapshot，不落 D 单命令执行器。
    win32 下内部快照可能 127（方案 B 原样上抛仍 executed），故断言"未被 REJECTED + 产 tool_result"，
    跨平台稳健（结构化 diff 的确定性断言见 test_config_diff_aggregation）。
    """
    intent_json = json.dumps(
        {
            "intent": "config_diff_attempt",
            "confidence": 0.9,
            "need_observation": False,
            "candidate_tools": [{"name": "config.diff", "args": {"paths": ["/etc/hosts"]}}],
            "risk_hint": "low",
            "justification": "调用已接回的 config.diff",
        }
    )

    async def scenario() -> None:
        app = create_app()
        app.dependency_overrides[get_llm] = lambda: build_fake_llm(intent_json)
        async with lifespan(app):
            async with _client(app) as client:
                resp = await client.post("/api/chat", json={"message": "比对配置"})
                events = await _consume_sse(client, resp.json()["stream_url"])
                types = [t for t, _ in events]
                # 已注册 → 不再安全降级：不 REJECTED，且经聚合产 tool_result
                assert "rejected" not in types
                assert "tool_result" in types
        app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_config_diff_present_in_registry() -> None:
    """config.diff 已接回 /api/tools/registry（决策⑤摘除恢复）。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                items = (await client.get("/api/tools/registry")).json()
                names = {it["tool"] for it in items}
                assert "config.diff" in names
                assert "config.hash_snapshot" in names
                # 其余 os_ops 工具仍在
                assert "system.info" in names
                assert "disk.usage" in names

    asyncio.run(scenario())


# ---- 任务丁：fake planner 按关键词产 confirm 计划 -------------------------


async def _wait_state(registry, trace_id: str, target: str, timeout: float = 5.0) -> None:  # noqa: ANN001
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        session = registry.get(trace_id)
        if session is not None and session.orchestrator.state.value == target:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timeout waiting for {target}")


def _drain(queue) -> list:  # noqa: ANN001, ANN201
    out = []
    while not queue.empty():
        ev = queue.get_nowait()
        if ev is not None:
            out.append(ev)
    return out


def test_fake_planner_restart_produces_confirm_plan() -> None:
    """发"重启 nginx" → 真策略 confirm → WAIT_APPROVAL，await_approval 含 service.restart。"""
    from backend.app.api import app as app_module

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            registry = app_module.get_registry()
            bus = app_module.get_bus()
            async with _client(app) as client:
                trace_id = (
                    await client.post("/api/chat", json={"message": "重启 nginx 服务"})
                ).json()["trace_id"]
                await _wait_state(registry, trace_id, "WAIT_APPROVAL")
                assert registry.get(trace_id).orchestrator.pending_approval_role == "admin"
                events = _drain(bus.get(trace_id))
                await_ev = [e for e in events if e.type == "await_approval"]
                assert await_ev, "应 emit await_approval"
                tools = await_ev[0].data["tools"]
                assert any(t["tool"] == "service.restart" for t in tools)

    asyncio.run(scenario())


def test_fake_planner_default_allow_no_regression() -> None:
    """发"看下系统" → 仍 allow → verified（allow 路径无回归）。"""

    async def scenario() -> None:
        app = create_app()
        async with lifespan(app):
            async with _client(app) as client:
                resp = await client.post("/api/chat", json={"message": "看下系统"})
                events = await _consume_sse(client, resp.json()["stream_url"])
                types = [t for t, _ in events]
                assert "verified" in types
                assert "await_approval" not in types

    asyncio.run(scenario())
