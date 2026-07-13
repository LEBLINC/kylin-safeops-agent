"""真 LLM 客户端（L 域，阶段 5 核心）。

提供两种模式（默认 = 不联网测试桩，CI 友好），**由 `KYLIN_LLM_PROVIDER` env 切换**：

- `KYLIN_LLM_PROVIDER=fixture`（默认）：**不联网测试桩**。
  确定性 mock，按 user_intent 关键词返回标准 Intent JSON。
  包含**间接注入（日志投毒）**模式——验"真 LLM 被投毒也被地板拦死"。
- `KYLIN_LLM_PROVIDER=real`：**真端点**。
  env 注入 base_url / api_key / model，调真 OpenAI 兼容 /chat/completions。
  生产化由 L 域后续接 SSO/LDAP 后做。

> 历史口径 `KYLIN_LLM_TEST_FIXTURE`（true/false）只是 docstring 残留，**不是实际开关**——
> 实际开关是 `KYLIN_LLM_PROVIDER`（fixture/real）。本文件已统一为 `KYLIN_LLM_PROVIDER`。

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
        try:
            content = data["choices"][0]["message"]["content"]
        except (IndexError, KeyError) as exc:
            raise RuntimeError(f"invalid_response: {exc}") from exc
        return str(content)

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

    async def probe(
        self,
        timeout_s: float = 3.0,
        audit_sink: object | None = None,
    ) -> dict[str, object]:
        """主动探测真端点连通性（?probe=true 专用）。

        - 独立 budget（不走 _RateLimiter / _TokenCounter，probe 是运维专用调用）
        - S9：probe_error 只报 status_code / error class，不暴露原文
        - audit_sink（可选）：失败/超时落 SqliteAuditSink，phase=probe_failed，
          trace_id=probe-{epoch_ms}，payload 含 status_code/error_class/latency_ms/model；
          ok / skipped 不写审计（运维运维噪音最小）

        Returns dict with keys: probe_status, probe_latency_ms, probe_error, audit_trace_id
        """
        if self.is_fixture:
            return {
                "probe_status": "skipped",
                "probe_latency_ms": None,
                "probe_error": None,
                "audit_trace_id": None,
            }
        import time

        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        # 极轻量 prompt（探活用，不计费/不计 token cap）
        body = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(url, json=body, headers=headers)
            latency_ms = int((time.monotonic() - t0) * 1000)
            if resp.is_success:
                return {
                    "probe_status": "ok",
                    "probe_latency_ms": latency_ms,
                    "probe_error": None,
                    "audit_trace_id": None,
                }
            audit_trace_id = self._audit_probe_failure(
                audit_sink=audit_sink,
                probe_status="failed",
                latency_ms=latency_ms,
                error_detail=f"status_code={resp.status_code}",
            )
            return {
                "probe_status": "failed",
                "probe_latency_ms": latency_ms,
                # S9：只报状态码，不暴露 response body
                "probe_error": f"status_code={resp.status_code}",
                "audit_trace_id": audit_trace_id,
            }
        except httpx.TimeoutException:
            latency_ms = int((time.monotonic() - t0) * 1000)
            audit_trace_id = self._audit_probe_failure(
                audit_sink=audit_sink,
                probe_status="timeout",
                latency_ms=latency_ms,
                error_detail="TimeoutException",
            )
            return {
                "probe_status": "timeout",
                "probe_latency_ms": latency_ms,
                "probe_error": "TimeoutException",
                "audit_trace_id": audit_trace_id,
            }
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.monotonic() - t0) * 1000)
            error_detail = type(exc).__name__
            audit_trace_id = self._audit_probe_failure(
                audit_sink=audit_sink,
                probe_status="failed",
                latency_ms=latency_ms,
                error_detail=error_detail,
            )
            return {
                "probe_status": "failed",
                "probe_latency_ms": latency_ms,
                "probe_error": error_detail,
                "audit_trace_id": audit_trace_id,
            }

    def _audit_probe_failure(
        self,
        *,
        audit_sink: object | None,
        probe_status: str,
        latency_ms: int,
        error_detail: str,
    ) -> str | None:
        """probe 失败/超时时落 SqliteAuditSink（运维历史可见）。

        防御纵深：audit_sink 为 None 时静默跳过（fake sink / 测试路径）；append
        抛错时仅 log warn 不抛（审计失败不杀 probe 响应，S8 一致性）。
        S9：error_detail 是 type(exc).__name__ 或 status_code=NNN（已 sanitize），
        绝不暴露 base_url/api_key/response body。

        Returns 写入的 audit trace_id（audit_sink=None 或 append 失败 → None）
        """
        if audit_sink is None:
            return None
        # audit_sink 鸭子类型取 append；非 AuditSink 实现 → 静默
        append_fn = getattr(audit_sink, "append", None)
        if not callable(append_fn):
            return None

        # probe-{epoch_ms}：秒级 epoch 足够区分（probe 是低频运维操作）
        import time

        trace_id = f"probe-{int(time.time() * 1000)}"
        # payload 严格控制字段名 + 不含凭据；status_code / error_class 已 sanitize
        # (HTTP status_code 是 int，error_class 是 type(exc).__name__)
        payload = {
            "probe_status": probe_status,
            "latency_ms": latency_ms,
            "error_detail": error_detail,
            "model": self.config.model,
            "base_url": self.config.base_url,  # 非凭据（运维需要看接哪个端点）
        }
        try:
            from backend.app.contracts.audit import (
                GENESIS_HASH,
                AuditRecord,
                compute_curr_hash,
            )

            curr_hash = compute_curr_hash(GENESIS_HASH, payload)
            record = AuditRecord(
                trace_id=trace_id,
                seq=0,
                phase="probe_failed",
                payload=payload,
                prev_hash=GENESIS_HASH,
                curr_hash=curr_hash,
            )
            append_fn(record)
            return trace_id
        except Exception as exc:  # noqa: BLE001
            # S8：审计失败不杀 probe 响应；log warn 即可
            logger.warning("probe audit append failed (S8 fail-closed 兜底): %s", exc)
            return None

    # ============================================================
    # 自然语言总结（verified 后调，仅前端聊天区展示）
    # ============================================================

    # S9 浅过滤黑名单（与 audit_logger._SENSITIVE_KEYS 同口径，阶段0独立维护）：
    # tool_results dict 内含 api_key / authorization / bind_password / secret /
    # token / password 这 6 类字段值调 LLM 前浅替换为 "***REDACTED***"；
    # key 名原样保留（非凭据）。
    _SENSITIVE_KEYS: frozenset[str] = frozenset(
        {"api_key", "authorization", "bind_password", "secret", "token", "password"}
    )

    @staticmethod
    def _sanitize_for_summary(tool_results: list[dict]) -> list[dict]:
        """S9 浅过滤 tool_results：6 类敏感字段值替换 ***REDACTED*** 后再喂 LLM。

        仅做 shallow dict 浅替换（顶层 key 命中即替换值；嵌套 dict/list 不递归——LLM 看 stdout
        摘要即可，工具结果里嵌套敏感值（如 args.api_key）已被 tool_args 闸/结果闸拦在 LLM 之前）。
        """
        if not tool_results:
            return tool_results
        sanitized: list[dict] = []
        for item in tool_results:
            if not isinstance(item, dict):
                sanitized.append(item)
                continue
            redacted = {
                k: ("***REDACTED***" if k.lower() in RealLLMClient._SENSITIVE_KEYS else v)
                for k, v in item.items()
            }
            sanitized.append(redacted)
        return sanitized

    async def summarize(self, tool_results: list[dict], user_intent: str) -> str | None:
        """真 LLM 自然语言总结（verified 后调，前端聊天区展示）。

        行为：
        - fixture 模式 → 返 "已完成:<tool_names>"（与 fake _fake_summary_fn 同口径，便于联调）
        - real 模式 → S9 浅过滤后 → 调 httpx POST /chat/completions（独立 timeout）；
          返回 str（LLM 输出）或 None（拒答 / 超时 / 异常）—— 由 orchestrator 决定 emit 是否，
          **不阻断** FINISHED 状态机（S8 fail-closed 不杀状态机）。
        - timeout 由 KYLIN_LLM_SUMMARIZE_TIMEOUT 覆盖（默认 5s）
        """
        summarize_timeout = float(_env_or("KYLIN_LLM_SUMMARIZE_TIMEOUT", "5"))
        sanitized = self._sanitize_for_summary(tool_results)

        if self.is_fixture:
            # fixture 也走 sanity 浅过滤后再固定排序输出（与 _fake_summary_fn 同结果）
            if not sanitized:
                return "已完成:（无工具结果）"
            names = sorted({str(r.get("tool", "?")) for r in sanitized if isinstance(r, dict)})
            return f"已完成:{','.join(names)}"

        # 真端点
        system_prompt = (
            "你是运维总结员，将工具执行结果归纳为一段话给用户。"
            "**绝不输出任何凭据**，S9 已被前置过滤。"
        )
        user_prompt = (
            "工具结果:\n"
            + json.dumps(sanitized, ensure_ascii=False, indent=2)
            + "\n\n用户意图:\n"
            + user_intent
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        body = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 256,
        }
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=summarize_timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return str(content) if content else None
        except (httpx.HTTPError, KeyError, IndexError, TimeoutError):
            # 拒答 / 超时 / 协议异常 → None，orchestrator 不 emit 不阻断 FINISHED
            return None


__all__ = [
    "CompletionFn",
    "RealLLMConfig",
    "RealLLMClient",
    "load_real_llm_config_from_env",
]
