"""阶段5 收尾 · GET /api/llm/health（健康检查端点）。

设计红线（开场合 §2.2 + 收尾工单）：
1. **绝不发 httpx POST 到真端点**——health 会被高频轮询；真调会耗 token /
   触发 _RateLimiter、有副作用。仅报配置态。
2. **绝不回显 api_key**（S9 铁律）——只回 `api_key_configured: bool`。
3. base_url 非密钥可回显。
4. `status: "ok"` 仅表示"配置可读"，**不**证明真端点可达——真连通性探测
   需额外 `?probe=true` 显式开关（留 backlog，本工单不交付）。
5. 复用既有依赖：verify_token（proxy 模式要求反代签名头）、tags=["llm"]。

C3 边界：本文件**只读** backend.app.llm.real_client（不修改其逻辑）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.deps import verify_token
from backend.app.api.schemas import LLMHealth

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get(
    "/health",
    response_model=LLMHealth,
    summary="LLM 健康检查（仅配置态；不探测真端点）",
)
async def llm_health(
    # 与 /api/system/overview 同款认证（proxy 模式要求反代签名头；dev 联调放行）。
    # verify_token 返回 user str（mode-aware）——本端点只用其"已认证"语义，不取身份。
    _user: str = Depends(verify_token),  # noqa: ARG001
) -> LLMHealth:
    """返回当前进程加载的 LLM 配置——**仅**配置态。

    不会调用 completion_fn，不会 await httpx。运维轮询友好：高频调用零 token
    消耗、零端点负载。

    Returns:
        LLMHealth：provider/model/base_url/limits + api_key_configured(bool)。

    Side effects: 无。
    """
    # 延迟 import：避免 router import 期就把 real_client 拉进依赖图。
    from backend.app.llm.real_client import load_real_llm_config_from_env

    cfg = load_real_llm_config_from_env()
    return LLMHealth(
        provider=cfg.provider,
        model=cfg.model,
        base_url=cfg.base_url,
        # S9：只报"是否配置了"，绝不回显 key 本身。
        api_key_configured=bool(cfg.api_key),
        rate_limit_per_minute=cfg.rate_limit_per_minute,
        token_cap=cfg.token_cap,
        status="ok",
    )
