"""契约 5：审计记录 + 哈希链（手册 §1.3）。

orchestrator 在每个状态转移点产出 / D 的 audit_logger 落库。

哈希链定义：H_i = SHA256(H_{i-1} || D_i)
其中 D_i 为第 i 条记录 payload 的规范化 JSON，H_{i-1} 为前一条链值；
任一中间记录被改，后续链值全部对不上（防篡改）。

payload 为结构化推理摘要（非原始思维链），字段固定为：
user_intent / risk_level / observations / decision / tool_plan / approval_required。
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

#: 链首记录的前置哈希（创世值）。
GENESIS_HASH = "0" * 64


def canonical_json(payload: dict) -> str:
    """payload 的规范化 JSON：键排序 + 紧凑分隔符 + 非 ASCII 原样。

    规范化是哈希链可复算的前提；D 落库与校验须用同一实现。
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_curr_hash(prev_hash: str, payload: dict) -> str:
    """计算 curr_hash = SHA256(prev_hash || canonical_json(payload))。"""
    data = prev_hash + canonical_json(payload)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class AuditRecord(BaseModel):
    """单条审计记录，构成不可篡改的哈希链。"""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(..., description="单次请求的全链路追踪 id")
    seq: int = Field(..., ge=0, description="链内序号，自 0 递增")
    phase: str = Field(..., description="状态机阶段名")
    payload: dict = Field(..., description="结构化推理摘要（非原始思维链）")
    prev_hash: str = Field(..., description="前一条记录的 curr_hash（链首为 GENESIS_HASH）")
    curr_hash: str = Field(..., description="SHA256(prev_hash || canonical_json(payload))")
