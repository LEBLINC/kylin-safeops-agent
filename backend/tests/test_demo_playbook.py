"""D16 — 四场景演示剧本回归测试：保证一键剧本跑通，防演示当天翻车。

仅断言终态与执行序（happy-path 管道串联）；不写"安全拦截"硬断言——
那由 L1 哨兵(test_e2e_real_policy.py)在 D 真 evaluate 合入后验证。
事件打印交给脚本本身（此处不校验 stdout）。
"""

from __future__ import annotations

import asyncio

from backend.app.agent.state_machine import State
from scripts.demo_config_drift_playbook import run_playbook as run_config_drift
from scripts.demo_disk_full_playbook import run_playbook as run_disk_full
from scripts.demo_disk_io_playbook import run_playbook as run_disk_io
from scripts.demo_zombie_process_playbook import run_playbook as run_zombie


def test_scenario1_disk_full_finished() -> None:
    """场景①磁盘满：观测→压缩轮转(R2)→审批→执行→FINISHED。"""
    state, calls = asyncio.run(run_disk_full())
    assert state is State.FINISHED
    assert calls == ["disk.usage", "log.compress_rotate"]


def test_scenario2_zombie_process_finished() -> None:
    """场景②僵尸进程：观测 process.list→重启父服务(R3 admin)→FINISHED。"""
    state, calls = asyncio.run(run_zombie())
    assert state is State.FINISHED
    assert calls == ["process.list", "service.restart"]


def test_scenario3_disk_io_finished() -> None:
    """场景③磁盘 I/O（近似）：观测 process.list(cpu)→重启服务(R3)→FINISHED。"""
    state, calls = asyncio.run(run_disk_io())
    assert state is State.FINISHED
    assert calls == ["process.list", "service.restart"]


def test_scenario4_config_drift_finished() -> None:
    """场景④配置漂移：单段只读 hash_snapshot+diff(R0 allow)→FINISHED（无审批）。

    决策⑤：config.diff 在 mcp 层聚合（复用 config.hash_snapshot，不落执行器），
    故 DemoExecutor 收到的是两次 config.hash_snapshot（第二次系 config.diff 聚合内部所发）。
    """
    state, calls = asyncio.run(run_config_drift())
    assert state is State.FINISHED
    assert calls == ["config.hash_snapshot", "config.hash_snapshot"]
