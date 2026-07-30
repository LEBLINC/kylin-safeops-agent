"""契约 3：策略裁决（手册 §1.3）。

策略引擎产出 / orchestrator 消费 / 前端渲染。
本文件含 PolicyEngine 最小桩：仅为让 orchestrator 能空跑，不写实现（实现归 backend/app/security）。
三态决策：allow / deny / confirm（shield 的 warn 归并入 allow）。
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.tool import RiskLevel

Decision = Literal["allow", "deny", "confirm"]


class PolicyVerdict(BaseModel):
    """策略引擎对单个工具调用的裁决结果。"""

    model_config = ConfigDict(extra="forbid")

    decision: Decision = Field(..., description="三态裁决：allow/deny/confirm")
    final_risk: RiskLevel = Field(..., description="综合后的最终风险等级")
    matched_rules: list[str] = Field(
        default_factory=list, description="命中的 rule_id 列表（前端展示）"
    )
    reason: str = Field(..., description="裁决理由")
    safer_alternative: str | None = Field(default=None, description="更安全的替代建议（可选）")
    approval_required: bool = Field(..., description="是否需人工确认")
    approval_role: str | None = Field(default=None, description='confirm 时谁能批，如 "admin"')


@runtime_checkable
class PolicyEngine(Protocol):
    """策略引擎接口（桩）。

    实现在 backend/app/security；此处仅定义契约，
    使 orchestrator 可依赖注入并空跑。契约层不实现本接口。
    """

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        """对单个候选工具调用做策略裁决。"""
        ...

    def rules(self) -> list[Any]:
        """返回当前生效的规则列表（commit 3 增量：/api/policy/rules 用）。"""
        ...
