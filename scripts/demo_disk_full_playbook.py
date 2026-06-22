"""D16 场景① — 磁盘满：观测 disk.usage(R0) → 规划 log.compress_rotate(R2) →
confirm/operator → 审批 → 执行 → VERIFIED（一键跑）。

跑在 fake 上（公共装配见 scripts/_demo_common.py）。D/X 真件到位后翻真三处：
- 策略 → backend.app.security 的 PolicyEngine(DEFAULT_POLICY, registry)；
- Executor → D 的特权代理 Executor；
- LLM → 真实端点（backend.app.llm.adapter 默认 httpx 实现 + LLMConfig）。

运行：python -m scripts.demo_disk_full_playbook   （仓库根目录下执行）
"""

from __future__ import annotations

import asyncio
import json

from backend.app.agent.state_machine import State
from scripts._demo_common import drive

# 两段式剧本意图：先观测磁盘（只读），再规划压缩轮转（R2 变更，触发审批）。
_OBSERVE_INTENT = json.dumps(
    {
        "intent": "diagnose_disk_full",
        "confidence": 0.95,
        "need_observation": True,
        "candidate_tools": [{"name": "disk.usage", "args": {}}],
        "risk_hint": "low",
        "justification": "先观测各挂载点占用，定位满盘分区",
    }
)
_ACTION_INTENT = json.dumps(
    {
        "intent": "reclaim_disk_space",
        "confidence": 0.9,
        "need_observation": False,
        "candidate_tools": [{"name": "log.compress_rotate", "args": {"path": "/var/log"}}],
        "risk_hint": "medium",
        "justification": "据观测，/var/log 占用偏高，压缩轮转回收空间",
    }
)


async def run_playbook() -> tuple[State, list[str]]:
    """场景①主链路：观测→规划→审批→执行→verified。返回 (终态, 执行序)。"""
    return await drive(
        title="场景①｜用户报『磁盘满了，帮我处理』",
        user_message="磁盘满了，帮我清理一下",
        intents=[_OBSERVE_INTENT, _ACTION_INTENT],
        trace_id="demo-disk-full",
    )


def main() -> None:
    state, _calls = asyncio.run(run_playbook())
    if state is not State.FINISHED:
        raise SystemExit(f"演示未达 FINISHED，实际：{state.value}")


if __name__ == "__main__":
    main()
