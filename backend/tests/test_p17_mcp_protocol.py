"""P1-7: MCP 协议面（JSON-RPC 2.0）——赛题核心要求的运行时落地。

修前：仓内有 to_mcp_tool() 转换函数，但**无任何运行时协议端点**。
赛题要求"基于 MCP 协议"，评委用 curl 发 JSON-RPC 拿不到任何响应——
能力写好了，协议面是空的。这是本轮唯一能改变赛题大项定性的缺口。

验收线（工单原文）：20 行 curl 能 initialize + tools/list 拿到 15 个工具
（inputSchema 驼峰 + meta 内 risk/requires_roles），
tools/call 非只读工具回标准 JSON-RPC error 而非裸 500。

  M-1 initialize 返回 protocolVersion + capabilities + serverInfo
  M-2 tools/list 返回全部 15 个工具
  M-3 inputSchema 用驼峰（MCP 规范），不是内部契约的 input_schema
  M-4 meta 内携带 risk / requires_roles（安全扩展字段）
  M-5 tools/call 只读工具正常执行，返回 content[].text
  M-6 tools/call 非只读工具 → JSON-RPC error（不是裸 500、不是 200 静默不执行）
  M-7 未知方法 → -32601；非法 JSON → -32700（协议自洽）
  M-8 tools/call 未知工具 → -32602
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from mcp_servers.os_ops import all_specs


def _post(payload: dict | str) -> dict:
    """向 MCP 端点发一条 JSON-RPC 请求，返回响应 JSON。"""
    from backend.app.api._fakes import build_gateway
    from backend.app.api.app import create_app, get_gateway, lifespan

    async def _scenario() -> dict:
        app = create_app()
        app.dependency_overrides[get_gateway] = build_gateway
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                if isinstance(payload, str):
                    resp = await client.post(
                        "/mcp", content=payload, headers={"Content-Type": "application/json"}
                    )
                else:
                    resp = await client.post("/mcp", json=payload)
                return resp.json()

    old = os.environ.get("KYLIN_AUTH_MODE")
    os.environ["KYLIN_AUTH_MODE"] = "dev"
    try:
        return asyncio.run(_scenario())
    finally:
        if old is None:
            os.environ.pop("KYLIN_AUTH_MODE", None)
        else:
            os.environ["KYLIN_AUTH_MODE"] = old


def test_m1_initialize() -> None:
    """M-1: initialize 握手返回协议版本与能力声明。"""
    r = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert "result" in r, f"M-1: initialize 未返回 result：{r}"
    result = r["result"]
    assert result["protocolVersion"], "M-1: 缺 protocolVersion"
    assert "tools" in result["capabilities"], "M-1: capabilities 未声明 tools"
    assert result["serverInfo"]["name"], "M-1: 缺 serverInfo.name"


def test_m2_tools_list_returns_all_specs() -> None:
    """M-2: tools/list 必须返回注册表全部工具（数量与 all_specs 一致）。"""
    r = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert "result" in r, f"M-2: tools/list 未返回 result：{r}"
    tools = r["result"]["tools"]
    assert len(tools) == len(
        all_specs()
    ), f"M-2: tools/list 返回 {len(tools)} 个，注册表有 {len(all_specs())} 个"


def test_m3_input_schema_is_camel_case() -> None:
    """M-3: MCP 规范用 inputSchema（驼峰），不是内部契约的 input_schema。"""
    r = _post({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
    tools = r["result"]["tools"]
    for tool in tools:
        assert "inputSchema" in tool, f"M-3: {tool['name']} 缺驼峰 inputSchema"
        assert (
            "input_schema" not in tool
        ), f"M-3: {tool['name']} 漏出了内部字段名 input_schema（MCP 客户端不认）"


def test_m4_meta_carries_security_fields() -> None:
    """M-4: meta 内携带 risk / requires_roles，MCP 客户端可据此做前置判断。"""
    r = _post({"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}})
    tools = r["result"]["tools"]
    for tool in tools:
        meta = tool.get("meta", {}).get("kylin_safeops", {})
        assert meta.get("risk"), f"M-4: {tool['name']} meta 缺 risk"
        assert meta.get("requires_roles"), f"M-4: {tool['name']} meta 缺 requires_roles"


def test_m5_tools_call_readonly_executes() -> None:
    """M-5: 只读工具经 tools/call 正常执行并返回 content。"""
    r = _post(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "system.info", "arguments": {}},
        }
    )
    assert "result" in r, f"M-5: 只读工具调用失败：{r}"
    content = r["result"]["content"]
    assert content and content[0]["type"] == "text", f"M-5: content 形态不符：{content}"


def test_m6_tools_call_change_tool_returns_jsonrpc_error() -> None:
    """M-6: 非只读工具必须回标准 JSON-RPC error，不是裸 500 也不是静默 200。

    这是工单点名的验收线：协议面必须自洽，客户端靠 error.code 分支。
    """
    r = _post(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "service.restart", "arguments": {"service_name": "nginx"}},
        }
    )
    assert "error" in r, f"M-6: 变更类工具未回 JSON-RPC error：{r}"
    assert r["error"]["code"] == -32000, f"M-6: 错误码应为 -32000，实际 {r['error']['code']}"
    assert r["id"] == 6, "M-6: error 响应必须回带原 id"


def test_m7_protocol_self_consistency() -> None:
    """M-7: 未知方法 -32601；非法 JSON -32700。"""
    r = _post({"jsonrpc": "2.0", "id": 7, "method": "no/such/method", "params": {}})
    assert r["error"]["code"] == -32601, f"M-7: 未知方法码错：{r}"

    r2 = _post("{not valid json")
    assert r2["error"]["code"] == -32700, f"M-7: 解析错误码错：{r2}"


def test_m8_unknown_tool_invalid_params() -> None:
    """M-8: tools/call 未知工具 → -32602（参数非法）。"""
    r = _post(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "no.such.tool", "arguments": {}},
        }
    )
    assert r["error"]["code"] == -32602, f"M-8: 未知工具码错：{r}"


@pytest.mark.parametrize("method", ["initialize", "tools/list"])
def test_m9_id_echoed_back(method: str) -> None:
    """M-9: JSON-RPC id 必须原样回带（客户端靠它匹配请求响应）。"""
    r = _post({"jsonrpc": "2.0", "id": "abc-123", "method": method, "params": {}})
    assert r["id"] == "abc-123", f"M-9: {method} 未回带 id：{r}"
