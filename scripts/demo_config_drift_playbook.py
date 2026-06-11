"""D16 场景④ — 配置漂移：config.hash_snapshot + config.diff(R0) → 检出漂移 →
只读报告 → VERIFIED（一键跑）。

单段式：全只读(R0) → 策略 allow → 整批执行（无变更、无审批）→ VERIFIED → FINISHED。
叙事：对关键配置取哈希快照并与基线对比，报告新增/删除/变更（只读诊断，不改配置）。

跑在 fake 上（公共装配见 scripts/_demo_common.py）。D/X 真件到位后翻真三处：
- 策略 → backend.app.security 的 PolicyEngine(DEFAULT_POLICY, registry)；
- Executor → D 的特权代理 Executor；
- LLM → 真实端点（backend.app.llm.adapter 默认 httpx 实现 + LLMConfig）。

运行：python -m scripts.demo_config_drift_playbook   （仓库根目录下执行）
"""

from __future__ import annotations

import asyncio
import json

from backend.app.agent.state_machine import State
from scripts._demo_common import drive

_PATHS = ["/etc/nginx/nginx.conf", "/etc/ssh/sshd_config"]

# 单段式只读意图：快照 + 与基线 diff（两个 R0 工具，原子批次全 allow）。
_INTENT = json.dumps(
    {
        "intent": "detect_config_drift",
        "confidence": 0.92,
        "need_observation": False,
        "candidate_tools": [
            {"name": "config.hash_snapshot", "args": {"paths": _PATHS}},
            {
                "name": "config.diff",
                "args": {"paths": _PATHS, "baseline_id": "baseline-2026-06-01"},
            },
        ],
        "risk_hint": "low",
        "justification": "对关键配置取哈希并与基线对比，只读检出漂移（不改配置）",
    }
)


async def run_playbook() -> tuple[State, list[str]]:
    """场景④主链路：单段只读 → allow → 执行 → verified。返回 (终态, 执行序)。"""
    return await drive(
        title="场景④｜用户问『最近改过哪些配置？有没有被人动过』",
        user_message="帮我看看关键配置有没有被改动（漂移）",
        intents=[_INTENT],
        trace_id="demo-config-drift",
        approve=False,  # 全只读，无审批闸
    )


def main() -> None:
    state, _calls = asyncio.run(run_playbook())
    if state is not State.FINISHED:
        raise SystemExit(f"演示未达 FINISHED，实际：{state.value}")


if __name__ == "__main__":
    main()
