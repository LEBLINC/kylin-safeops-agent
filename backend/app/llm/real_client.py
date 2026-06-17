"""真 LLM 客户端（L 域，阶段 5 核心）。

提供两种模式（默认 = 不联网测试桩，CI 友好）：
- **不联网测试桩**（`KYLIN_LLM_TEST_FIXTURE=true`，默认）：
  确定性 mock，按 user_intent 关键词返回标准 Intent JSON。
  包含**间接注入（日志投毒）**模式——验"真 LLM 被投毒也被地板拦死"。
- **真端点**（`KYLIN_LLM_TEST_FIXTURE=false`）：env 注入 base_url/api_key/model，
  调真 OpenAI 兼容 /chat/completions。生产化由 L 域后续接 SSO/LDAP 后做。

rate limit + token cap：
- `KYLIN_LLM_RATE_LIMIT=10`（每分钟最多 10 次 LLM 调用，超出 raise RuntimeError）；
- `KYLIN_LLM_TOKEN_CAP=100000`（单次会话累计 100k tokens 后拒）。
S9：所有密钥走 env，绝不入库（与 S9 铁律一致）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

#: 完成函数类型（与 backend.app.llm.adapter.CompletionFn 一致）。
CompletionFn = Callable[[list[dict[str, str]]], Awaitable[str]]


# ============================================================
# 真 LLM 配置
# ============================================================


@dataclass
class RealLLMConfig:
    """真 LLM 客户端配置（env 注入，S9 绝不入库）。"""

    provider: str = "real"  # "real" = 真端点；"fixture" = 不联网测试桩
    base_url: str = "http://localhost:8000/v1"
    model: str = "qwen2.5"
    api_key: str = ""  # env 注入
    timeout: float = 30.0
    temperature: float = 0.1
    max_tokens: int = 1024
    rate_limit_per_minute: int = 10
    token_cap: int = 100_000


def _env_or(key: str, default: str) -> str:
    """读 env string，空白/空时回退 default（避免 KYLIN_X='' 走 falsy 默认）。"""
    v = os.environ.get(key)
    if v is None or not v.strip():
        return default
    return v.strip()


def load_real_llm_config_from_env() -> RealLLMConfig:
    """从环境变量装配 RealLLMConfig（S9 一处集中读 env，便于测试 monkeypatch）。"""
    _provider = os.environ.get("KYLIN_LLM_PROVIDER", "fixture").strip().lower() or "fixture"
    return RealLLMConfig(
        provider=_provider,
        base_url=_env_or("KYLIN_LLM_BASE_URL", "http://localhost:8000/v1"),
        model=_env_or("KYLIN_LLM_MODEL", "qwen2.5"),
        api_key=_env_or("KYLIN_LLM_API_KEY", ""),
        timeout=float(_env_or("KYLIN_LLM_TIMEOUT", "30")),
        temperature=float(_env_or("KYLIN_LLM_TEMPERATURE", "0.1")),
        max_tokens=int(_env_or("KYLIN_LLM_MAX_TOKENS", "1024")),
        rate_limit_per_minute=int(_env_or("KYLIN_LLM_RATE_LIMIT", "10")),
        token_cap=int(_env_or("KYLIN_LLM_TOKEN_CAP", "100000")),
    )


# ============================================================
# 不联网测试桩（默认；CI 友好；含间接注入样本）
# ============================================================

# service_name 提取：取首个空白分词后、直到结尾或下一个非字母数字字符
_SERVICE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]*")
# path 提取：取首个 ^/... 形式的绝对路径
_PATH_RE = re.compile(r"(/[A-Za-z0-9._/@-]+)")


def _parse_service_name(content: str) -> str | None:
    """从 `重启 <name>` / `restart <name>` 后的 token 里提取 service_name。"""
    for kw in ("重启", "restart"):
        idx = content.find(kw)
        if idx < 0:
            continue
        tail = content[idx + len(kw) :].strip()
        for filler in (
            "一下",
            "下",
            "服务",
            "服务吧",
            "吧",
            "服务下",
            "，",
            "。",
            ",",
        ):
            if tail.startswith(filler):
                tail = tail[len(filler) :].strip()
        m = _SERVICE_NAME_RE.match(tail)
        if m:
            token = m.group(0)
            if "." not in token and "_" not in token and "-" not in token:
                return f"{token}.service"
            return token
    return None


def _parse_path(content: str) -> str | None:
    """从 message 里提取首个以 / 开头的绝对路径。"""
    m = _PATH_RE.search(content)
    return m.group(1) if m else None


def _fixture_intent_for_message(content: str) -> str:
    """按关键词返回标准 Intent JSON（确定性、CI 友好）。

    包含：
    - D-10 注入样本 → user_intent 直接命中高，注入闸拦在 LLM 之前；
    - **★间接注入样本** → 模拟"日志投毒"：返回包含危险命令的 Intent，
      验"结果闸 is_untrusted 包裹 + 策略闸 deny 兜底"任一即合规。
    """
    # ★间接注入样本：用户问"先看 syslog 决定如何压缩"——LLM 模拟投毒，
    # 真的把 syslog 内容（投毒 payload）当成"用户意图"返回。
    # 测试期望：结果闸 is_untrusted=True 隔离；策略闸命中 CMD001 deny 兜底。
    if "syslog" in content and ("投毒" in content or "决定如何" in content):
        return json.dumps(
            {
                "intent": "log_poisoning_attempt",
                "confidence": 0.7,
                "need_observation": False,
                "candidate_tools": [
                    {
                        "name": "log.compress_rotate",
                        "args": {
                            "path": "/var/log/syslog",
                            "_poisoned_note": "rm -rf /",  # 投毒 payload
                        },
                    }
                ],
                "risk_hint": "medium",
                "justification": "真 LLM 模拟被 syslog 投毒诱导。",
            }
        )
    if any(kw in content for kw in ("重启", "restart")):
        svc = _parse_service_name(content) or "cron.service"
        return json.dumps(
            {
                "intent": "service_restart",
                "confidence": 0.9,
                "need_observation": False,
                "candidate_tools": [{"name": "service.restart", "args": {"service_name": svc}}],
                "risk_hint": "high",
                "justification": f"重启 {svc}（真 LLM fixture，R3→confirm/admin）",
            }
        )
    if any(kw in content for kw in ("压缩", "轮转", "rotate", "清日志", "清理日志")):
        path = _parse_path(content) or "/var/log/app.log"
        return json.dumps(
            {
                "intent": "log_compress_rotate",
                "confidence": 0.9,
                "need_observation": False,
                "candidate_tools": [{"name": "log.compress_rotate", "args": {"path": path}}],
                "risk_hint": "medium",
                "justification": f"压缩轮转 {path}（真 LLM fixture，R2→confirm/operator）",
            }
        )
    if any(kw in content for kw in ("查看磁盘", "磁盘占用", "disk")):
        return json.dumps(
            {
                "intent": "disk_usage",
                "confidence": 0.9,
                "need_observation": False,
                "candidate_tools": [{"name": "disk.usage", "args": {}}],
                "risk_hint": "low",
                "justification": "查看磁盘占用（真 LLM fixture，R0 allow）",
            }
        )
    if any(kw in content for kw in ("查", "查询", "lsof")):
        lsof_path = _parse_path(content) or "/var/log/app.log"
        return json.dumps(
            {
                "intent": "check_open_files",
                "confidence": 0.9,
                "need_observation": False,
                "candidate_tools": [{"name": "file.lsof_check", "args": {"path": lsof_path}}],
                "risk_hint": "low",
                "justification": f"lsof {lsof_path}（真 LLM fixture，R0 allow）",
            }
        )
    return json.dumps(
        {
            "intent": "system_info",
            "confidence": 0.9,
            "need_observation": False,
            "candidate_tools": [{"name": "system.info", "args": {}}],
            "risk_hint": "low",
            "justification": "查看系统基本信息（真 LLM fixture）",
        }
    )


# ============================================================
# Rate limiter + token cap
# ============================================================


class _RateLimiter:
    """每分钟最多 N 次调用的滑动窗口计数器（线程/协程安全）。"""

    def __init__(self, max_per_minute: int) -> None:
        self._max = max_per_minute
        self._calls: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.time()
            self._calls = [t for t in self._calls if now - t < 60.0]
            if len(self._calls) >= self._max:
                raise RuntimeError(f"rate limit exceeded: {self._max}/min")
            self._calls.append(now)


class _TokenCounter:
    """累计 token 数（简化口径 = 消息字符数 / 4），超 cap raise。"""

    def __init__(self, cap: int) -> None:
        self._cap = cap
        self._used = 0

    def add(self, text: str) -> None:
        self._used += max(1, len(text) // 4)
        if self._used > self._cap:
            raise RuntimeError(f"token cap exceeded: {self._used} > {self._cap}")

    @property
    def used(self) -> int:
        return self._used


# ============================================================
# 真 LLM 客户端
# ============================================================


class RealLLMClient:
    """真 LLM 客户端（fixture 默认；真端点 opt-in）。

    使用：
      cfg = load_real_llm_config_from_env()
      client = RealLLMClient(cfg)
      adapter = LLMAdapter(completion_fn=client.completion_fn)
    """

    def __init__(self, config: RealLLMConfig | None = None) -> None:
        self.config = config or RealLLMConfig()
        self._rate = _RateLimiter(self.config.rate_limit_per_minute)
        self._tokens = _TokenCounter(self.config.token_cap)
        self._http: httpx.AsyncClient | None = None  # lazy；测试可 patch

    @property
    def is_fixture(self) -> bool:
        return self.config.provider == "fixture"

    @property
    def tokens_used(self) -> int:
        return self._tokens.used

    async def completion_fn(self, messages: list[dict[str, str]]) -> str:
        """completion_fn（接 LLMAdapter.completion_fn）。

        - fixture 模式 → _fixture_intent_for_message（确定性，不联网）；
        - real 模式 → httpx 调 OpenAI 兼容 /chat/completions。
        - 每次调前 rate limit + token 计数；超 cap raise。
        """
        await self._rate.acquire()
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = str(msg.get("content", ""))
                break
        self._tokens.add(json.dumps(messages, ensure_ascii=False))

        if self.is_fixture:
            return _fixture_intent_for_message(last_user)

        # 真端点
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        body = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.config.timeout)
        try:
            resp = await self._http.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        finally:
            # 一次调用释放；下次再建（轻量；测试 mock client.post）
            if self._http is not None:
                await self._http.aclose()
                self._http = None
        return str(data["choices"][0]["message"]["content"])

    async def health_check(self) -> dict[str, str]:
        """健康检查（接 GET /api/llm/health）。"""
        if self.is_fixture:
            return {"status": "ok", "mode": "fixture", "model": self.config.model}
        return {
            "status": "ok",
            "mode": "real",
            "model": self.config.model,
            "base_url": self.config.base_url,
        }


__all__ = [
    "CompletionFn",
    "RealLLMConfig",
    "RealLLMClient",
    "load_real_llm_config_from_env",
]
