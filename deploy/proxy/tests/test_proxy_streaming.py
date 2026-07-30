"""之七十五 H-9: 反代非 SSE 响应流式转发守门。

H-9 前 proxy.py 的非 SSE 分支是 `b"".join([chunk async for chunk in ...])`——
把整个上游响应读进内存才回发。两个后果：
  1. 内存：大响应（审计导出 / 工具调用列表）在反代侧翻倍占用
  2. 延迟：首字节延迟 == 上游总耗时，边到边的优势全丢

本用例用 httpx MockTransport 造一个"分块 + 每块之间有延迟"的上游。

注意一个实测坑：MockTransport 会在交给被测代码之前就把 stream 物化，因此
"首字节延迟"这类 ASGI 级计时**无法**区分流式与整体缓冲（实测两版 chunk 到达
时刻逐位相同）。故 H9-1 改为断言 body_iterator 的类型这一结构性差别。

  H9-1 路由 return 时上游尚未被拉取（真流式，非整体缓冲）
  H9-2 非 SSE 响应内容完整、status/content-type 正确透传（流式不丢数据）
  H9-3 源码层：非 SSE 分支不得再出现整体缓冲的 b"".join
  H9-4 SSE 分支仍走 _sse_heartbeat 流式（H-9 不得回退既有能力）
  H9-5 client 生命周期：不得用 async with 包住 StreamingResponse
       （return 后 body 才被消费，async with 会提前关连接）
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import os

import httpx
import pytest

# 测试卫生：proxy.py 有模块级 ADR-0004 fail-fast（KYLIN_LDAP_MOCK=true 且无
# opt-out 即拒绝 import），故 import 前必须先置 env。但这三个变量**绝不能泄漏到
# 进程全局**——KYLIN_LDAP_MOCK=true 会让其它测试的 app lifespan 撞上同一条
# ADR-0004 硬阻断（实测泄漏时全量 29 个用例连带失败）。
# 故：临时置入 → import → 立即恢复原值。
_SAVED = {k: os.environ.get(k) for k in ("KYLIN_LDAP_MOCK", "KYLIN_PROXY_ALLOW_MOCK")}
os.environ["KYLIN_LDAP_MOCK"] = "true"
os.environ["KYLIN_PROXY_ALLOW_MOCK"] = "true"
os.environ.setdefault("KYLIN_PROXY_AUTH_SECRET", "a" * 64)
try:
    from deploy.proxy import proxy as P  # noqa: E402
finally:
    for _k, _v in _SAVED.items():
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:kylin123").decode()}
_CHUNKS = 5
_CHUNK_SIZE = 1000
_DELAY = 0.12


class _CountingByteStream(httpx.AsyncByteStream):
    """可观测的假上游：记录已被拉取的块数。

    这是区分"流式"与"整体缓冲"的关键探针——路由函数 return 的那一刻：
      流式  → 上游一块都还没被拉（yielded == 0，等 ASGI 层消费时才拉）
      缓冲  → 上游已被读干（yielded == _CHUNKS，数据全在内存里了）
    """

    def __init__(self) -> None:
        self.yielded = 0

    async def __aiter__(self):
        for _ in range(_CHUNKS):
            await asyncio.sleep(_DELAY)
            self.yielded += 1
            yield b"x" * _CHUNK_SIZE


_last_stream: list[_CountingByteStream] = []


def _mock_upstream(request: httpx.Request) -> httpx.Response:
    stream = _CountingByteStream()
    _last_stream.append(stream)
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        stream=stream,
    )


@pytest.fixture
def patched_client(monkeypatch: pytest.MonkeyPatch):
    """把 proxy 内部构造的 AsyncClient 换成走 MockTransport 的实例。

    LDAP mock 用 monkeypatch 打在**实例属性**上，不改 env：
    LdapClient.__init__ 只在构造时读一次 KYLIN_LDAP_MOCK（ldap_client.py:156），
    而 proxy.py 的 client 是 import 期就构造好的，此后改 env 无效。
    改 env 还有副作用——KYLIN_LDAP_MOCK=true 泄漏到进程全局会让其它测试的
    app lifespan 撞上 ADR-0004 硬阻断（实测泄漏时 29 个用例连带失败）。
    直接钉实例属性，作用域精确到本用例，零全局副作用。
    """
    monkeypatch.setattr(P.ldap_client, "mock", True, raising=False)
    real_cls = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_cls(*args, transport=httpx.MockTransport(_mock_upstream), **kwargs)

    monkeypatch.setattr(P.httpx, "AsyncClient", _factory)


def test_h9_1_upstream_not_consumed_at_return(patched_client) -> None:
    """H9-1: 反代返回的 body 必须是"尚未耗尽的异步生成器"，而非已成型 bytes。

    为什么不用"首字节延迟"计时判定：httpx.MockTransport 在交给被测代码之前就把
    stream 物化，实测流式版与整体缓冲版的 chunk 到达时刻逐位相同
    （0.13/0.25/0.38/0.50/0.62）——任何走 MockTransport 的 ASGI 级计时都区分不出
    二者，那种断言是自欺。

    也不能只看 body_iterator 有没有 __anext__：Starlette 会用
    iterate_in_threadpool 把同步迭代器也包成异步的，该断言恒真、等于没测。

    可靠的探针是**上游被拉取的进度**——路由 return 的那一刻：
      流式  → 上游 0 块被拉（等 ASGI 层消费时才拉）
      缓冲  → 上游已被读干（数据全在内存）
    已用变异测试确认：把实现改回 b"".join 整体缓冲，本用例即转红。
    """
    from starlette.requests import Request

    _last_stream.clear()
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/api/audit/export",
        "raw_path": b"/api/audit/export",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [
            (b"authorization", _AUTH["Authorization"].encode()),
            (b"accept", b"application/json"),
            (b"host", b"proxy"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("proxy", 80),
    }

    async def _receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _drive():
        request = Request(scope, receive=_receive)
        return await P.proxy_route(request, "api/audit/export")

    response = asyncio.run(_drive())

    assert response.status_code == 200
    assert _last_stream, "H9-1: 假上游未被调用"
    yielded_at_return = _last_stream[-1].yielded
    assert yielded_at_return == 0, (
        f"H9-1: 路由 return 时上游已被拉取 {yielded_at_return}/{_CHUNKS} 块——"
        "说明响应被整体读进内存（未流式透传）"
    )

    # 补证：body 确实还能完整读出（流式不是"读不到"）
    async def _consume() -> int:
        total = 0
        async for chunk in response.body_iterator:
            total += len(chunk) if isinstance(chunk, bytes) else len(chunk.encode())
        return total

    assert asyncio.run(_consume()) == _CHUNKS * _CHUNK_SIZE
    assert _last_stream[-1].yielded == _CHUNKS, "H9-1: 消费后上游应已读完"


def test_h9_2_non_sse_content_and_headers_intact(patched_client) -> None:
    """H9-2: 流式改造不得丢数据、不得改 status / content-type。"""

    async def _drive() -> httpx.Response:
        transport = httpx.ASGITransport(app=P.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as c:
            return await c.get("/api/tools/calls", headers=_AUTH)

    r = asyncio.run(_drive())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.content == b"x" * (_CHUNKS * _CHUNK_SIZE)


def _code_lines(fn) -> str:
    """取函数源码但剔除注释行——避免断言被注释里的字面量干扰。"""
    out = []
    for line in inspect.getsource(fn).splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def test_h9_3_no_whole_body_buffering_in_source() -> None:
    """H9-3: 源码层守门——非 SSE 分支不得再整体缓冲（注释不计入）。"""
    code = _code_lines(P.proxy_route)
    assert 'b"".join' not in code, 'H9-3: 非 SSE 分支仍在 b"".join 整体缓冲'
    assert "resp.aiter_bytes()" in code, "H9-3: 应流式透传 aiter_bytes()"


def test_h9_4_sse_branch_still_streams() -> None:
    """H9-4: SSE 分支仍走 _sse_heartbeat（既有能力不得回退）。"""
    src = inspect.getsource(P.proxy_route)
    assert "_sse_heartbeat(resp.aiter_bytes())" in src
    assert "text/event-stream" in src


def test_h9_5_client_not_closed_before_body_consumed() -> None:
    """H9-5: 不得用 async with 持有 client。

    StreamingResponse 的 body 在本函数 return **之后**才被 ASGI 层消费；
    async with 会在 return 时关掉 client，流未读完连接就断。正确做法是
    手工持有 + BackgroundTask 在响应发完后释放。
    """
    code = _code_lines(P.proxy_route)
    assert (
        "async with httpx.AsyncClient" not in code
    ), "H9-5: async with 会在 return 时关闭 client，流式 body 尚未消费"
    assert "BackgroundTask(_release)" in code, "H9-5: 应由 BackgroundTask 释放 resp + client"

    # 释放顺序只看 _release 内部（函数体里还有一处 except 分支的 client.aclose()，
    # 那是"send 失败、resp 尚不存在"的清理路径，不参与本判定）。
    release_body = code[code.index("async def _release") : code.index("if is_sse")]
    assert release_body.index("resp.aclose()") < release_body.index(
        "client.aclose()"
    ), "H9-5: _release 必须先 aclose(resp) 再 aclose(client)（先关 client 会掐断流）"
