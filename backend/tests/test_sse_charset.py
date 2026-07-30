"""SSE Content-Type charset 守门（前端 A7 修复）。

回归用例：SSE 响应 Content-Type 必须含 charset=utf-8，
避免浏览器按 Latin-1 解码中文（justification / reason / natural_language.text）。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.event_bus import EventBus, SSEEventSink
from backend.app.api.routers.chat import router as chat_router
from backend.app.contracts.stream import StreamEvent


def test_sse_response_content_type_includes_charset_utf8() -> None:
    """X A7：chat.py /api/chat/{trace_id}/events 必须返回 charset=utf-8 Content-Type。

    字节流本身 UTF-8（pydantic model_dump_json 默认 ensure_ascii=False）；
    缺 charset 浏览器按 Latin-1 解 → 中文乱码。

    实现策略：app_module 注入 _bus + get_bus override，绕过 lifespan。
    """
    import backend.app.api.app as app_module

    bus = EventBus()
    trace_id = "t-charset"
    bus.create(trace_id)
    sink = SSEEventSink(bus=bus, trace_id=trace_id)
    sink.emit(
        StreamEvent(
            trace_id=trace_id,
            type="verified",
            ts=1.0,
            data={"summary": "磁盘占用查看完成"},
        )
    )
    bus.close(trace_id)

    # 注入全局 _bus 让 get_bus() 拿到我们的 instance
    original_bus = app_module._bus
    app_module._bus = bus
    try:
        app = FastAPI()
        app.include_router(chat_router)
        with TestClient(app) as client:
            with client.stream("GET", f"/api/chat/{trace_id}/events") as resp:
                assert resp.status_code == 200
                content_type = resp.headers["content-type"]
                assert "text/event-stream" in content_type
                assert "charset=utf-8" in content_type
    finally:
        app_module._bus = original_bus


def test_sse_payload_chinese_bytes_preserved() -> None:
    """SSE 字节流必须含 UTF-8 中文原文（不被 latin-1 截断或转义）。"""
    import backend.app.api.app as app_module

    bus = EventBus()
    trace_id = "t-bytes"
    bus.create(trace_id)
    sink = SSEEventSink(bus=bus, trace_id=trace_id)
    sink.emit(
        StreamEvent(
            trace_id=trace_id,
            type="verified",
            ts=1.0,
            data={"summary": "磁盘占用查看完成,已压缩 1.2GB"},
        )
    )
    bus.close(trace_id)

    original_bus = app_module._bus
    app_module._bus = bus
    try:
        app = FastAPI()
        app.include_router(chat_router)
        with TestClient(app) as client:
            with client.stream("GET", f"/api/chat/{trace_id}/events") as resp:
                chunks: list[bytes] = []
                for chunk in resp.iter_bytes():
                    chunks.append(chunk)
                body = b"".join(chunks)
        # UTF-8 中文必须原样出现在字节流
        assert "磁盘占用查看完成".encode() in body
        assert b"1.2GB" in body
    finally:
        app_module._bus = original_bus


def test_sse_media_type_source_has_charset() -> None:
    """源码静态校验：chat.py 媒体类型声明必须含 charset=utf-8（防回归）。"""
    from pathlib import Path

    src = Path("backend/app/api/routers/chat.py").read_text(encoding="utf-8")
    matches = [line for line in src.splitlines() if "text/event-stream" in line]
    assert matches, "chat.py 应含 media_type=text/event-stream 行"
    for line in matches:
        assert "charset=utf-8" in line, f"chat.py 缺 charset=utf-8: {line!r}"
