"""L3 — 演示剧本回归测试：保证一键剧本跑到 FINISHED，防演示当天翻车。

仅断言主链路终态与执行序，事件打印交给脚本本身（此处不校验 stdout）。
"""

from __future__ import annotations

import asyncio

from backend.app.agent.state_machine import State
from scripts.demo_disk_full_playbook import run_playbook


def test_demo_playbook_reaches_finished() -> None:
    """磁盘满剧本：观测→规划→审批→执行→verified，终态 FINISHED。"""
    state = asyncio.run(run_playbook())
    assert state is State.FINISHED
