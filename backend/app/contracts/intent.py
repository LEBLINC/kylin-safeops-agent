"""契约 2：LLM 结构化意图（手册 §1.3）。

planner 产出 / orchestrator 消费。
铁律：本契约绝不包含裸 shell / 命令字符串字段；LLM 只能产出
「工具名 + 结构化参数 + 理由」。任何工具调用须命中已注册 ToolSpec.name。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# LLM 对意图危险度的主观提示（非最终裁决；最终 RiskLevel 由策略引擎给）。
RiskHint = Literal["low", "medium", "high"]


class CandidateTool(BaseModel):
    """LLM 提议调用的单个工具：仅工具名 + 结构化参数，绝不含裸 shell。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="须匹配已注册 ToolSpec.name")
    args: dict = Field(default_factory=dict, description="结构化参数，按 input_schema 校验")


class Intent(BaseModel):
    """LLM 规划阶段输出的强类型意图对象。"""

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(..., description='意图标识，如 "clean_system_garbage"')
    confidence: float = Field(..., ge=0.0, le=1.0, description="模型自评置信度 [0,1]")
    need_observation: bool = Field(..., description="是否需先调用只读观测工具再规划")
    candidate_tools: list[CandidateTool] = Field(
        default_factory=list,
        max_length=32,
        description=(
            "候选工具调用列表；上限 32（注册表共 15 工具，留 2 倍余量容同工具"
            "不同参数的重复调用；超限即视为规划本身不合理，不是资源保护线）"
        ),
    )
    risk_hint: RiskHint = Field(..., description="LLM 主观风险提示")
    justification: str = Field(..., description="选择该规划的理由")
