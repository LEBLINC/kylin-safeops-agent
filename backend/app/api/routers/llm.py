"""GET /api/llm/health（健康检查端点，含 ?probe=true 连通性探测）。

设计红线：
1. 默认（无 probe 参数）→ 只报配置态，绝不发 httpx。
2. ?probe=true + fixture → probe_status="skipped"（fixture 无真端点）。
3. ?probe=true + real → 真发一次轻量 POST（独立 budget，不走 _RateLimiter / _TokenCounter）。
4. S9：api_key 只报 bool；probe_error 只报 status_code / error class，不暴露原文。
5. probe 失败时不 raise（运维友好：标 failed/timeout，不崩服务）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.api.deps import verify_token
from backend.app.api.schemas import LLMHealth, LLMHealthProbe

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get(
    "/health",
    summary="LLM 健康检查（配置态；?probe=true 时真探端点连通性）",
)
async def llm_health(
    _user: str = Depends(verify_token),  # noqa: ARG001
    probe: bool = Query(default=False, description="true → 真探端点连通性（real 模式）"),
) -> LLMHealthProbe | LLMHealth:
    """返回 LLM 配置态；?probe=true 时额外真探端点可达性。

    无 probe：返回 LLMHealth（6 字段，不发 httpx）。
    probe=true：返回 LLMHealthProbe（LLMHealth + probe_* 字段）。
    """
    from backend.app.llm.real_client import RealLLMClient, load_real_llm_config_from_env

    cfg = load_real_llm_config_from_env()
    base = LLMHealth(
        provider=cfg.provider,
        model=cfg.model,
        base_url=cfg.base_url,
        api_key_configured=bool(cfg.api_key),
        rate_limit_per_minute=cfg.rate_limit_per_minute,
        token_cap=cfg.token_cap,
        status="ok",
    )

    if not probe:
        return base

    # probe=true 路径
    import os

    timeout_s = float(os.environ.get("KYLIN_LLM_PROBE_TIMEOUT", "3"))
    client = RealLLMClient(cfg)
    result = await client.probe(timeout_s=timeout_s)
    return LLMHealthProbe(
        **base.model_dump(),
        probe_enabled=not client.is_fixture,
        probe_status=result["probe_status"],  # type: ignore[arg-type]
        probe_latency_ms=result["probe_latency_ms"],  # type: ignore[arg-type]
        probe_error=result["probe_error"],  # type: ignore[arg-type]
    )
