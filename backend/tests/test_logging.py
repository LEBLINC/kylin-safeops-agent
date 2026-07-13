"""B4 commit 2 守门测试: JSON formatter + trace_id contextvar."""

from __future__ import annotations

import io
import json
import logging

from backend.app.main_logging import (
    _JsonFormatter,
    get_trace_id,
    reset_trace_id,
    set_trace_id,
)


def test_t3_logging_json_format() -> None:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(_JsonFormatter())
    test_logger = logging.getLogger("test_t3")
    test_logger.setLevel(logging.INFO)
    test_logger.addHandler(handler)
    test_logger.propagate = False
    try:
        test_logger.info("hello world", extra={"trace_id": "abc123", "phase": "RECEIVED"})
    finally:
        test_logger.removeHandler(handler)
        test_logger.propagate = True
    output = buf.getvalue().strip()
    assert output, "T3 expected log output"
    obj = json.loads(output)
    assert obj["message"] == "hello world"
    assert obj["level"] == "INFO"
    assert obj["logger"] == "test_t3"
    assert obj["trace_id"] == "abc123"


def test_t4_trace_id_contextvar_isolated() -> None:
    assert get_trace_id() == ""
    token = set_trace_id("trace-test-4")
    try:
        assert get_trace_id() == "trace-test-4"
    finally:
        reset_trace_id(token)
    assert get_trace_id() == ""
