"""D16 场景③ — 磁盘 I/O 高负载（★近似演示，见下方工具集限制）。

⚠️ 工具集限制（S2 红线：不臆造工具）：当前 os_ops 13 工具中【无 iostat/iotop 类
真正的 I/O 感知工具】。故本场景以"用 process.list 按 cpu 降序定位高占用进程 →
重启其服务"作为【近似演示】，叙事上代表"定位 I/O/CPU 异常的元凶进程并处置"。
TODO(BLOCKED 待补 I/O 感知工具)：补 io.stat / io.top（R0/R1）后，本剧本观测段应
换为真实 I/O 指标采集，再据此规划处置。是否补该工具交 L 判。

管道：观测 process.list(R0, sort_by=cpu) → 规划 service.restart(R3) →
confirm/admin → 审批 → 执行 → VERIFIED。

跑在 fake 上（公共装配见 scripts/_demo_common.py）。D/X 真件到位后翻真三处：
- 策略 → backend.app.security 的 PolicyEngine(DEFAULT_POLICY, registry)；
- Executor → D 的特权代理 Executor；
- LLM → 真实端点（backend.app.llm.adapter 默认 httpx 实现 + LLMConfig）。

运行：python -m scripts.demo_disk_io_playbook   （仓库根目录下执行）
"""

from __future__ import annotations

import asyncio
import json

from backend.app.agent.state_machine import State
from scripts._demo_common import drive

# 观测：进程按 cpu 降序取 top（近似定位 I/O/CPU 异常元凶；只读 R0）。
_OBSERVE_INTENT = json.dumps(
    {
        "intent": "diagnose_high_io",
        "confidence": 0.85,
        "need_observation": True,
        "candidate_tools": [{"name": "process.list", "args": {"sort_by": "cpu", "top_n": 10}}],
        "risk_hint": "low",
        "justification": "近似：按 cpu 降序定位高占用进程（受限于无 I/O 感知工具）",
    }
)
# 行动：重启元凶进程所属服务（R3 变更，需 admin 审批）。
_ACTION_INTENT = json.dumps(
    {
        "intent": "mitigate_high_io",
        "confidence": 0.82,
        "need_observation": False,
        "candidate_tools": [
            {"name": "service.restart", "args": {"service_name": "batch-indexer.service"}}
        ],
        "risk_hint": "high",
        "justification": "重启高占用元凶服务 batch-indexer 以缓解 I/O 压力",
    }
)


async def run_playbook() -> tuple[State, list[str]]:
    """场景③主链路（近似）：观测→规划→审批(admin)→执行→verified。返回 (终态, 执行序)。"""
    return await drive(
        title="场景③｜用户报『磁盘 I/O 一直很高，系统很卡』（近似演示）",
        user_message="磁盘 IO 很高系统很卡，帮我看看",
        intents=[_OBSERVE_INTENT, _ACTION_INTENT],
        trace_id="demo-disk-io",
    )


def main() -> None:
    state, _calls = asyncio.run(run_playbook())
    if state is not State.FINISHED:
        raise SystemExit(f"演示未达 FINISHED，实际：{state.value}")


if __name__ == "__main__":
    main()
