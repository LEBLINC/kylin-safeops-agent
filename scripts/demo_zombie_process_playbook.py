"""D16 场景② — 僵尸进程：观测 process.list(R0) 定位父进程 → 规划 service.restart(R3) →
confirm/admin → 审批 → 执行 → VERIFIED（一键跑）。

叙事：僵尸进程(defunct)无法被 kill，须重启其父服务回收。观测列进程定位父进程，
再规划重启对应 systemd 服务（高危 R3，需 admin 审批）。

跑在 fake 上（公共装配见 scripts/_demo_common.py）。D/X 真件到位后翻真三处：
- 策略 → backend.app.security 的 PolicyEngine(DEFAULT_POLICY, registry)；
- Executor → 特权执行器；
- LLM → 真实端点（backend.app.llm.adapter 默认 httpx 实现 + LLMConfig）。

运行：python -m scripts.demo_zombie_process_playbook   （仓库根目录下执行）
"""

from __future__ import annotations

import asyncio
import json

from backend.app.agent.state_machine import State
from scripts._demo_common import drive

# 观测：列进程（只读 R0）定位僵尸进程及其父服务。
_OBSERVE_INTENT = json.dumps(
    {
        "intent": "diagnose_zombie_processes",
        "confidence": 0.93,
        "need_observation": True,
        "candidate_tools": [{"name": "process.list", "args": {"sort_by": "cpu"}}],
        "risk_hint": "low",
        "justification": "列出进程，定位 defunct 僵尸进程及其父进程所属服务",
    }
)
# 行动：重启父服务回收僵尸（R3 变更，需 admin 审批）。
_ACTION_INTENT = json.dumps(
    {
        "intent": "reap_zombies_via_restart",
        "confidence": 0.9,
        "need_observation": False,
        "candidate_tools": [
            {"name": "service.restart", "args": {"service_name": "app-worker.service"}}
        ],
        "risk_hint": "high",
        "justification": "僵尸进程无法直接 kill，重启其父服务 app-worker 回收",
    }
)


async def run_playbook() -> tuple[State, list[str]]:
    """场景②主链路：观测→规划→审批(admin)→执行→verified。返回 (终态, 执行序)。"""
    return await drive(
        title="场景②｜用户报『系统里有一堆僵尸进程清不掉』",
        user_message="系统里好多僵尸进程，帮我清理",
        intents=[_OBSERVE_INTENT, _ACTION_INTENT],
        trace_id="demo-zombie-process",
    )


def main() -> None:
    state, _calls = asyncio.run(run_playbook())
    if state is not State.FINISHED:
        raise SystemExit(f"演示未达 FINISHED，实际：{state.value}")


if __name__ == "__main__":
    main()
