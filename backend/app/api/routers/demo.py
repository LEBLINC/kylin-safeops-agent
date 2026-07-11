"""L 域 /api/demo/* 3 接口（commit 4 增量）。

覆盖：prepare / run / cleanup。
认证：admin-only（决策⑨ mode-aware + RBAC 二次校验）。
沙箱阻断：KYLIN_SANDBOX_ENABLED=1 时拒（沙箱环境不允许 demo——demo 会改审计库）。
复用 scripts.demo_stage4_e2e._SCENARIOS 场景定义（A/B/C/D/E，F 跳过防破坏审计）。
"""

from __future__ import annotations

import asyncio
import importlib
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.auth import Principal
from backend.app.api.deps import require_proxy_identity
from backend.app.api import schemas

router = APIRouter(prefix="/api/demo", tags=["demo"])


# 仅 admin 可调（demo 是污染性操作——临时审计库 / fake 用户 / temp sandbox）
def _require_admin(principal: Principal) -> None:
    if "admin" not in {r.lower() for r in principal.roles}:
        raise HTTPException(
            status_code=403,
            detail=(
                f"demo endpoints require admin role; got roles={sorted(principal.roles)}. "
                "防 demo 污染审计库：admin-only。"
            ),
        )


def _require_no_sandbox() -> None:
    """KYLIN_SANDBOX_ENABLED=1 时拒：沙箱环境不允许 demo（demo 会改真审计库）。"""
    if os.environ.get("KYLIN_SANDBOX_ENABLED", "").strip() == "1":
        raise HTTPException(
            status_code=409,
            detail=(
                "KYLIN_SANDBOX_ENABLED=1 时拒绝 demo（沙箱环境不允许改审计库）。"
                "演示请先 unset KYLIN_SANDBOX_ENABLED。"
            ),
        )


@router.post("/{scenario}/prepare", response_model=schemas.DemoPrepareResponse)
async def prepare_scenario(
    scenario: str,
    principal: Principal = Depends(require_proxy_identity),
) -> schemas.DemoPrepareResponse:
    """为指定 scenario 准备环境：返回临时审计库路径 + fake 用户列表。

    实际不落盘任何文件——只返约定路径，前端拿到路径后传 /run 即可。
    沙箱阻断 + admin-only 校验。
    """
    _require_admin(principal)
    _require_no_sandbox()
    if scenario not in {"A", "B", "C", "D", "E"}:
        raise HTTPException(status_code=404, detail=f"unknown scenario: {scenario}")
    # 临时审计库路径（实际执行时由 scenario 函数内部使用）
    tmp_dir = tempfile.mkdtemp(prefix=f"kylin-demo-{scenario}-")
    audit_path = str(Path(tmp_dir) / "audit.db")
    return schemas.DemoPrepareResponse(
        scenario=scenario,
        audit_db_path=audit_path,
        tmp_dir=tmp_dir,
        ready=True,
        by=principal.user,
    )


@router.post("/{scenario}/run", response_model=schemas.DemoRunResponse)
async def run_scenario(
    scenario: str,
    principal: Principal = Depends(require_proxy_identity),
) -> schemas.DemoRunResponse:
    """执行指定 scenario：动态 import scripts.demo_stage4_e2e，调对应 async 函数。

    返回 {scenario, status, state, verified_summary, record_count, ...}。
    沙箱阻断 + admin-only 校验 + scenario 名白名单（A/B/C/D/E 五个，F 跳过防破坏）。
    """
    _require_admin(principal)
    _require_no_sandbox()
    if scenario not in {"A", "B", "C", "D", "E"}:
        raise HTTPException(
            status_code=404,
            detail=f"unknown scenario: {scenario}（仅支持 A/B/C/D/E）",
        )
    try:
        mod = importlib.import_module("scripts.demo_stage4_e2e")
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"failed to import demo module: {exc}") from exc
    scenarios = getattr(mod, "_SCENARIOS", {})
    if scenario not in scenarios:
        raise HTTPException(status_code=500, detail=f"scenario {scenario} not in _SCENARIOS")
    label, fn = scenarios[scenario]
    try:
        result: dict[str, Any] = await fn()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"scenario {scenario} failed: {exc}") from exc
    return schemas.DemoRunResponse(
        scenario=scenario,
        label=str(label),
        by=principal.user,
        state=str(result.get("state", "UNKNOWN")),
        verified_summary=str(result.get("verified_summary", "")),
        record_count=int(result.get("record_count", 0)),
        rejected_cause=str(result.get("rejected_cause", "")),
        raw=result,
    )


@router.post("/{scenario}/cleanup", response_model=schemas.DemoCleanupResponse)
async def cleanup_scenario(
    scenario: str,
    principal: Principal = Depends(require_proxy_identity),
) -> schemas.DemoCleanupResponse:
    """清理 demo 临时文件（临时审计库 + tmp_dir）。

    不强求必须先 prepare——幂等操作，找不到就返 not_found=True。
    沙箱阻断 + admin-only 校验。
    """
    _require_admin(principal)
    _require_no_sandbox()
    # 清理 /tmp/kylin-demo-{scenario}-* 目录
    tmp_root = Path(tempfile.gettempdir())
    removed: list[str] = []
    for d in tmp_root.glob(f"kylin-demo-{scenario}-*"):
        if d.is_dir():
            try:
                import shutil  # noqa: PLC0415

                shutil.rmtree(d)
                removed.append(str(d))
            except OSError:
                pass
    return schemas.DemoCleanupResponse(
        scenario=scenario,
        by=principal.user,
        removed_dirs=removed,
    )
