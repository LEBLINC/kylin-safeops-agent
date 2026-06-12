"""链校验结果模型（F3 铁律：字段名用 valid，不用 ok）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChainVerifyResult(BaseModel):
    """verify_chain 的结构化返回。

    broken_seq 为第一个出错记录的 seq（链完好为 None）；
    reason 说明出错类型（篡改 / 重排 / 断链 / 缺号 / GENESIS 不符），完好为空串。
    """

    model_config = ConfigDict(extra="forbid")

    valid: bool = Field(..., description="哈希链是否完好")
    trace_id: str = Field(..., description="被校验的 trace id")
    record_count: int = Field(..., ge=0, description="该 trace 的记录条数")
    broken_seq: int | None = Field(default=None, description="第一个出错记录的 seq")
    reason: str = Field(default="", description="出错原因；链完好为空串")
