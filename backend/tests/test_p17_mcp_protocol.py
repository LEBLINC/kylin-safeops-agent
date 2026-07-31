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

#: MCP 端点路径（随 router.prefix；M-0 钉住它必须在 /api/ 下）
_MCP_PATH = "/api/mcp"


def _post(payload: dict | str, *, role: str = "admin") -> dict:
    """向 MCP 端点发一条 JSON-RPC 请求，返回响应 JSON。"""
    from backend.app.api._fakes import build_gateway
    from backend.app.api.app import create_app, get_gateway, lifespan

    async def _scenario() -> dict:
        app = create_app()
        app.dependency_overrides[get_gateway] = build_gateway
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                headers = {"X-User-Role": role}
                if isinstance(payload, str):
                    resp = await client.post(
                        _MCP_PATH,
                        content=payload,
                        headers={**headers, "Content-Type": "application/json"},
                    )
                else:
                    resp = await client.post(_MCP_PATH, json=payload, headers=headers)
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


def test_m0_route_must_live_under_api_prefix() -> None:
    """M-0: MCP 路由必须落在 /api/ 前缀下——否则生产拓扑不可达。

    nginx 只有两个 location：/api/ 转 sidecar，/ 是 SPA 静态回退
    （try_files，无 proxy_pass）。挂在 /api/ 之外的路由，评委
    curl -X POST https://host/... 会命中静态回退拿到 index.html 或 405，
    永远到不了后端——本轮全部 ASGI 直连用例都测不出这一层。

    刻意钉前缀而非字面量 /api/mcp：路由名可以再改，"必须在 /api/ 下"
    是部署拓扑决定的硬约束。
    """
    from backend.app.api.routers.mcp import router

    assert router.prefix.startswith("/api/"), (
        f"M-0: MCP 路由前缀是 {router.prefix!r}，不在 /api/ 下——"
        f"nginx 的 / location 是 SPA 静态回退，该路由在生产不可达"
    )


def test_m10_rbac_parity_with_tools_call() -> None:
    """M-10: MCP tools/call 必须与 /api/tools/call 挂同一道工具级 RBAC。

    P1-6 给人工直调路径接上工具级 RBAC 后，MCP 是第二条人工直调路径。
    若只有只读门，"只读⟹viewer可调"只是当前 15 个工具的数据巧合
    （R0/R1 恰好全含 viewer），加一个只读但限 operator 的工具即分叉：
    /api/tools/call 403、/mcp 放行。此处钉住两条路径挂的是同一个依赖。
    """
    import inspect

    from backend.app.api.deps import principal_for_tool_call
    from backend.app.api.routers import mcp as mcp_mod
    from backend.app.api.routers import tools as tools_mod

    def _deps(fn) -> set:  # noqa: ANN001
        return {
            p.default.dependency
            for p in inspect.signature(fn).parameters.values()
            if hasattr(p.default, "dependency")
        }

    mcp_deps = _deps(mcp_mod.mcp_endpoint)
    tools_deps = _deps(tools_mod.post_tool_call)
    assert principal_for_tool_call in mcp_deps, (
        "M-10: MCP 端点未挂 principal_for_tool_call——缺工具级 RBAC，" "与 /api/tools/call 不同口径"
    )
    assert principal_for_tool_call in tools_deps, "M-10 前提：/api/tools/call 应挂该依赖"


def test_m11_rbac_actually_denies_insufficient_role() -> None:
    """M-11: RBAC 闸必须真的拦人——结构断言只证明"挂了"，这条证明"拦得住"。

    构造一个只读但要求 operator 的工具（现实里如"读敏感配置"），
    用 viewer 身份调：只读门放行，必须由 RBAC 闸拒。
    这正是 M-10 注释里说的分叉场景，此处让它可执行。
    """
    from backend.app.contracts.intent import CandidateTool
    from backend.app.contracts.policy import PolicyVerdict
    from backend.app.contracts.tool import ToolSpec
    from backend.app.contracts.untrusted import ToolResult
    from backend.app.mcp.gateway import MCPGateway
    from backend.app.mcp.registry import ToolRegistry

    spec = ToolSpec(
        name="config.read_secret",
        description="只读但限 operator 的敏感配置读取",
        risk="R0",  # 只读 → 只读门放行
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        requires_roles=["operator", "admin"],  # 不含 viewer
        reversible=True,
    )

    class _Policy:
        def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
            return PolicyVerdict(
                decision="allow",
                final_risk="R0",
                matched_rules=[],
                reason="ok",
                approval_required=False,
            )

    class _Executor:
        async def execute(self, tool: CandidateTool) -> ToolResult:
            return ToolResult(tool=tool.name, args=tool.args, exit_code=0, stdout_truncated="ok")

    def _gw() -> MCPGateway:
        return MCPGateway(ToolRegistry([spec]), _Policy(), _Executor())

    from backend.app.api.app import create_app, get_gateway, lifespan

    async def _call(role: str) -> dict:
        app = create_app()
        app.dependency_overrides[get_gateway] = _gw
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    _MCP_PATH,
                    json={
                        "jsonrpc": "2.0",
                        "id": 11,
                        "method": "tools/call",
                        "params": {"name": "config.read_secret", "arguments": {}},
                    },
                    headers={"X-User-Role": role},
                )
                return resp.json()

    old = os.environ.get("KYLIN_AUTH_MODE")
    os.environ["KYLIN_AUTH_MODE"] = "dev"
    try:
        denied = asyncio.run(_call("viewer"))
        allowed = asyncio.run(_call("operator"))
    finally:
        if old is None:
            os.environ.pop("KYLIN_AUTH_MODE", None)
        else:
            os.environ["KYLIN_AUTH_MODE"] = old

    assert "error" in denied, (
        f"M-11: viewer 调 requires_roles=[operator,admin] 的只读工具未被拒——"
        f"只读门放行了它，RBAC 闸没接上：{denied}"
    )
    assert denied["error"]["code"] == -32000, f"M-11: 应为策略拒绝码：{denied}"
    assert "result" in allowed, f"M-11: operator 有权调用却被拒：{allowed}"


def _post_proxy_mode(payload: dict) -> tuple[int, dict]:
    """在 **proxy 模式**下打 MCP 端点（造真签名头），返回 (status, json)。

    P0-D6 的教训：其余 MCP 用例全在 dev 模式，而 dev 分支直接从 X-User-Role
    造 Principal、根本不调 verify_proxy_identity——dev 模式测出来的东西
    证明不了生产分支。生产默认是 proxy，故关键路径必须有 proxy 版本。
    """
    import hashlib
    import hmac
    import json
    import time
    import uuid

    from backend.app.api._fakes import build_gateway
    from backend.app.api.app import create_app, get_gateway, lifespan

    secret = "mcp-proxy-mode-secret"
    body = json.dumps(payload).encode()
    user, roles, ts = "admin", "admin", str(int(time.time()))
    body_sha = hashlib.sha256(body).hexdigest()
    nonce = uuid.uuid4().hex
    canonical = f"{user}\n{roles}\n{ts}\nPOST\n{_MCP_PATH}\n{body_sha}\n{nonce}"
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-Auth-User": user,
        "X-Auth-Roles": roles,
        "X-Auth-Timestamp": ts,
        "X-Auth-Signature": sig,
        "X-Auth-Method": "POST",
        "X-Auth-Path": _MCP_PATH,
        "X-Auth-Body-Sha": body_sha,
        "X-Auth-Nonce": nonce,
        "Content-Type": "application/json",
    }

    async def _scenario() -> tuple[int, dict]:
        app = create_app()
        app.dependency_overrides[get_gateway] = build_gateway
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(_MCP_PATH, content=body, headers=headers)
                return resp.status_code, resp.json()

    old_mode = os.environ.get("KYLIN_AUTH_MODE")
    old_secret = os.environ.get("KYLIN_PROXY_AUTH_SECRET")
    os.environ["KYLIN_AUTH_MODE"] = "proxy"
    os.environ["KYLIN_PROXY_AUTH_SECRET"] = secret
    try:
        return asyncio.run(_scenario())
    finally:
        for key, val in (
            ("KYLIN_AUTH_MODE", old_mode),
            ("KYLIN_PROXY_AUTH_SECRET", old_secret),
        ):
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def test_m12_tools_list_in_proxy_mode() -> None:
    """M-12: proxy（生产默认）模式下 tools/list 必须真能打通。"""
    status, body = _post_proxy_mode(
        {"jsonrpc": "2.0", "id": 12, "method": "tools/list", "params": {}}
    )
    assert status != 401, f"M-12: proxy 模式下被 401——生产分支打不进去：{body}"
    assert "result" in body, f"M-12: 未返回 result：{body}"
    assert len(body["result"]["tools"]) == len(all_specs())


def test_m13_change_tool_denied_in_proxy_mode() -> None:
    """M-13: proxy 模式下变更类工具仍回 -32000（安全边界在生产分支同样生效）。"""
    status, body = _post_proxy_mode(
        {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {"name": "service.restart", "arguments": {"service_name": "nginx"}},
        }
    )
    assert status != 401, f"M-13: proxy 模式下被 401：{body}"
    assert body.get("error", {}).get("code") == -32000, f"M-13: 变更类工具未被拒：{body}"


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
