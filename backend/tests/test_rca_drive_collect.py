"""之六十八 Task 4.5: collect_rca_evidence 驱动守门 (4 用例)."""

from __future__ import annotations

import asyncio
from unittest import mock

from backend.app.agent.rca_drive import collect_rca_evidence


class _FakeGateway:
    def __init__(self, *, evaluate_results=None, read_only_map=None):
        self._evaluate_results = evaluate_results or {}
        self._read_only_map = read_only_map or {}
        self.evaluate_called = False
        self.call_args = []

    def evaluate(self, tool):
        self.evaluate_called = True
        return self._evaluate_results.get(
            tool.name, mock.Mock(decision="allow", reason="", final_risk="R0")
        )

    def is_read_only(self, tool):
        return self._read_only_map.get(tool.name, True)

    async def call(self, tool, *, approved=False):
        self.call_args.append((tool.name, tool.args, approved))
        return mock.Mock(
            executed=True,
            result=mock.Mock(tool=tool.name, args=tool.args, exit_code=0, stdout_truncated="ok"),
        )


class _FakeEngine:
    def __init__(self, plan=None):
        self._plan = plan
        self.get_scenario_plan_called = False

    def get_scenario_plan(self, problem_type):
        self.get_scenario_plan_called = True
        return self._plan


def _disk_full_plan():
    return {
        "problem_type": "disk_full",
        "evidence_steps": [
            {
                "tool": "disk.usage",
                "args": {},
                "purpose": "p",
                "evidence_key": "du",
                "required": True,
                "expected_signal": "e",
            },
            {
                "tool": "disk.large_files",
                "args": {"path": "/var/log"},
                "purpose": "p",
                "evidence_key": "lf",
                "required": True,
                "expected_signal": "e",
            },
        ],
    }


# ---- T-drive-1: scenario 命中 → evidence_steps 跑通 ----


def test_drive_1_scenario_plan_drives_readonly_collection() -> None:
    bus = _FakeGateway()
    eng = _FakeEngine(plan=_disk_full_plan())
    collected = asyncio.run(collect_rca_evidence(bus, eng, "disk full"))  # type: ignore[arg-type]
    assert len(collected) == 2
    assert eng.get_scenario_plan_called
    assert {c.tool for c in collected} == {"disk.usage", "disk.large_files"}


# ---- T-drive-2: 工具未注册 → evaluate deny → skip ----


def test_drive_2_unregistered_tool_skipped() -> None:
    deny_result = mock.Mock(decision="deny", reason="unknown tool", final_risk="?")
    bus = _FakeGateway(evaluate_results={"unknown.tool": deny_result})
    plan = {
        "problem_type": "disk_full",
        "evidence_steps": [
            {
                "tool": "unknown.tool",
                "args": {},
                "purpose": "p",
                "evidence_key": "u",
                "required": False,
                "expected_signal": "e",
            },
            {
                "tool": "disk.usage",
                "args": {},
                "purpose": "p",
                "evidence_key": "du",
                "required": True,
                "expected_signal": "e",
            },
        ],
    }
    eng = _FakeEngine(plan=plan)
    collected = asyncio.run(collect_rca_evidence(bus, eng, "disk full"))  # type: ignore[arg-type]
    assert len(collected) == 1
    assert collected[0].tool == "disk.usage"
    assert bus.call_args == [("disk.usage", {}, False)]


# ---- T-drive-3: 非只读工具 → is_read_only=False → skip ----


def test_drive_3_non_readonly_tool_skipped() -> None:
    # 场景内两个 step 都标为非只读 → 整轮 skip,call 不被调
    bus = _FakeGateway(read_only_map={"disk.usage": False, "disk.large_files": False})
    eng = _FakeEngine(plan=_disk_full_plan())
    collected = asyncio.run(collect_rca_evidence(bus, eng, "disk full"))  # type: ignore[arg-type]
    assert collected == []
    assert bus.call_args == []


# ---- T-drive-4: 无 problem_type resolvable → 整轮 skip ----


def test_drive_4_no_problem_type_skips_whole_round() -> None:
    bus = _FakeGateway()
    eng = _FakeEngine(plan=None)
    collected = asyncio.run(collect_rca_evidence(bus, eng, ""))  # type: ignore[arg-type]
    assert collected == []
    assert not eng.get_scenario_plan_called
    assert not bus.evaluate_called


# ---- T-drive-5: call 抛错 → skip,不抛错 ----


def test_drive_5_call_exception_does_not_propagate() -> None:
    async def _raising_call(tool, *, approved=False):
        raise RuntimeError("simulated gateway failure")

    bus = _FakeGateway()
    bus.call = _raising_call  # type: ignore[assignment]
    eng = _FakeEngine(plan=_disk_full_plan())
    collected = asyncio.run(collect_rca_evidence(bus, eng, "disk full"))  # type: ignore[arg-type]
    assert collected == []
