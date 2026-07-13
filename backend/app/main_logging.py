"""logging 集中配置（L-H16 + 阶段5 step 增量）。

设计要点:
- prod 模式走 JSON formatter (Loki/ELK 友好聚合)
- dev 模式走 console formatter (人眼友好)
- trace_id contextvar 抽 from context + extra,全局 SSE 事件带 trace_id

调用方: app.lifespan 启动时调 setup_logging()
- KYLIN_LOG_MODE=production  → JSON formatter
- KYLIN_LOG_MODE=development/dev (默认) → console formatter
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.config
import sys
from typing import Any

# L-H16: contextvar 抽 trace_id(每请求一格 + SSE 注入)
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def get_trace_id() -> str:
    """读当前 contextvar trace_id;为空串返"""
    return trace_id_var.get()


def set_trace_id(trace_id: str) -> contextvars.Token:
    """设 trace_id contextvar 返 Token(便于 finally reset)"""
    return trace_id_var.set(trace_id)


def reset_trace_id(token: contextvars.Token) -> None:
    """finally reset trace_id contextvar"""
    trace_id_var.reset(token)


class _JsonFormatter(logging.Formatter):
    """JSON formatter:每条日志 1 行 JSON;trace_id contextvar 自动注入。"""

    # 标准 LogRecord 属性(白名单)
    _STD_ATTRS = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = get_trace_id()
        if trace_id:
            log_obj["trace_id"] = trace_id
        # extra 字段(allowlist)- 非 std 属性
        for key, value in record.__dict__.items():
            if key in self._STD_ATTRS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                log_obj[key] = value
            except TypeError:
                log_obj[key] = repr(value)
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """注入 logging.dictConfig;按 KYLIN_LOG_MODE 切换 JSON vs console。"""
    # local import 防 shadowing 风险 (无 sys alias 在此函数体内)
    import os as _os

    mode = (_os.environ.get("KYLIN_LOG_MODE", "development") or "development").lower()
    is_prod = mode in ("production", "prod", "json")

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {"()": "backend.app.main_logging._JsonFormatter"},
            "console": {
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                "datefmt": "%H:%M:%S",
            },
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "json" if is_prod else "console",
            },
        },
        "root": {"handlers": ["stdout"], "level": level},
        # 特定 logger 调静默(避免 uvicorn.access 刷屏)
        "loggers": {
            "uvicorn.access": {"level": "WARNING"},
            "httpx": {"level": "WARNING"},
        },
    }
    logging.config.dictConfig(config)


__all__ = [
    "get_trace_id",
    "set_trace_id",
    "reset_trace_id",
    "setup_logging",
]
