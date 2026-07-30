"""契约 1：Tool 定义（手册 §1.3）。

MCP Gateway 产出 / 策略引擎读 / 前端读。
纯 Pydantic 模型 + 常量，无业务逻辑；本文件为工具静态描述的唯一事实来源。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 工具自身静态风险分级：R0(只读/无副作用) → R4(高危/不可逆/系统级)。
RiskLevel = Literal["R0", "R1", "R2", "R3", "R4"]


class ToolSpec(BaseModel):
    """单个工具的静态契约描述。

    input_schema 为强类型 JSON Schema，禁止任意路径/任意命令字段；
    路径类参数由各工具 schema 自行约束（canonicalize + 禁 ".." 在执行层兜底）。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description='工具名，形如 "disk.large_files"')
    description: str = Field(..., description="人类可读用途说明")
    risk: RiskLevel = Field(..., description="工具自身静态风险等级")
    input_schema: dict = Field(..., description="JSON Schema，强类型，禁任意路径/命令")
    requires_roles: list[str] = Field(
        ..., description='可调用该工具的角色，如 ["operator"] / ["admin"]'
    )
    reversible: bool = Field(..., description="是否可逆，作为风险评分输入")
