"""P1-10: 中文入口全链路不通——既有能力入不了口。

赛题原文的示例句"帮我清理系统垃圾"在当前实现里走不通，三处各断一截：

  ① _fakes 关键词表无"清理/垃圾/空间/满"→ 落到兜底 system.info，
     压根不是磁盘清理意图
  ② 七处 fake 意图全部 need_observation=False → "感知→再规划"闭环
     在演示路径上从未执行过一次（代码写好了，从没被走到）
  ③ rca_drive 的推断表是纯英文正则 → 五套 RCA 采证模板对中文输入全失效

三处都是"能力已实现但入不了口"，故本项修的是入口不是能力。

  Z-1 "帮我清理系统垃圾"识别为磁盘清理意图（不再落 system.info）
  Z-2 该意图要求观测 → 观测闭环真被执行
  Z-3 中文输入能推断出 disk_full 场景（RCA 采证模板可达）
  Z-4 五套场景的中文触发词逐个可达
  Z-5 英文推断不回归（原有能力不得被中文分支挤掉）
  Z-6 无关文本仍返回 None（防"含中文即判故障"的过宽实现）
  Z-7 端到端：该句真走出观测→再规划闭环并抵达终态
"""

from __future__ import annotations

import json

import pytest

from backend.app.agent.rca_drive import _infer_problem_type_from_intent


def _fake_intent(message: str) -> dict:
    from backend.app.api._fakes import _intent_for_message

    return json.loads(_intent_for_message(message))


#: 赛题原文示例句 + 常见同义说法
_CLEANUP_PHRASES = [
    "帮我清理系统垃圾",
    "磁盘满了，清理一下",
    "清理垃圾文件",
    "空间不足，帮我看看",
]


@pytest.mark.parametrize("message", _CLEANUP_PHRASES)
def test_z1_cleanup_phrases_not_fall_through_to_system_info(message: str) -> None:
    """Z-1: 清理类中文说法不得落到兜底 system.info。"""
    intent = _fake_intent(message)
    tools = [t["name"] for t in intent["candidate_tools"]]
    assert tools != ["system.info"], (
        f"Z-1: {message!r} 落到了兜底 system.info——赛题原文示例句在演示里"
        f"不会触发任何磁盘处置（intent={intent['intent']}）"
    )


@pytest.mark.parametrize("message", _CLEANUP_PHRASES)
def test_z2_cleanup_requires_observation(message: str) -> None:
    """Z-2: 清理类意图必须先观测再规划——不知道占用情况就不该直接动手。

    这同时是"感知→再规划"闭环在演示路径上被真正执行的唯一入口：
    七处 fake 意图此前全是 need_observation=False。
    """
    intent = _fake_intent(message)
    assert intent["need_observation"] is True, (
        f"Z-2: {message!r} 的 need_observation=False——" f"观测→再规划闭环代码写好了却从未被走到"
    )


#: 五套 RCA 场景的中文触发词
_ZH_SCENARIO_PHRASES = [
    ("磁盘满了", "disk_full"),
    ("帮我清理系统垃圾", "disk_full"),
    ("有僵尸进程", "zombie_process"),
    ("io 很高，系统很卡", "io_high"),
    ("配置漂移了", "config_drift"),
    ("服务挂了", "service_failure"),
]


@pytest.mark.parametrize(("phrase", "expected"), _ZH_SCENARIO_PHRASES)
def test_z3_chinese_infers_scenario(phrase: str, expected: str) -> None:
    """Z-3/Z-4: 中文输入必须能推断出场景，否则五套采证模板全部不可达。"""
    got = _infer_problem_type_from_intent(phrase)
    assert got == expected, f"Z-3: {phrase!r} 推断为 {got!r}，应为 {expected!r}"


#: 英文原有能力（回归守门）
_EN_SCENARIO_PHRASES = [
    ("disk full", "disk_full"),
    ("zombie process found", "zombie_process"),
    ("iowait high", "io_high"),
    ("config drift detected", "config_drift"),
    ("service failed", "service_failure"),
]


@pytest.mark.parametrize(("phrase", "expected"), _EN_SCENARIO_PHRASES)
def test_z5_english_inference_not_regressed(phrase: str, expected: str) -> None:
    """Z-5: 加中文分支不得挤掉原有英文推断。"""
    assert _infer_problem_type_from_intent(phrase) == expected


def test_z7_cleanup_walks_full_observation_loop() -> None:
    """Z-7: "帮我清理系统垃圾"端到端真走出观测→再规划闭环并抵达终态。

    Z-2 只验意图字段（need_observation=True），证明不了闭环真被执行——
    字段为真但编排不走观测，同样是断言假绿。这里跑真 orchestrator，
    断言 CONTEXT_COLLECTED 状态与 observation 事件都出现过。
    """
    import asyncio

    from backend.app.agent.orchestrator import Orchestrator
    from backend.app.agent.state_machine import State
    from backend.app.api._fakes import build_fake_llm, build_gateway

    class _Audit:
        def __init__(self) -> None:
            self.records: list = []

        def append(self, record) -> None:  # noqa: ANN001
            self.records.append(record)

    class _Events:
        def __init__(self) -> None:
            self.events: list = []

        def emit(self, event) -> None:  # noqa: ANN001
            self.events.append(event)

    audit, events = _Audit(), _Events()
    orch = Orchestrator(llm=build_fake_llm(), gateway=build_gateway(), audit=audit, events=events)

    end = asyncio.run(orch.run([{"role": "user", "content": "帮我清理系统垃圾"}]))

    phases = [r.phase for r in audit.records]
    types = [e.type for e in events.events]

    assert (
        State.CONTEXT_COLLECTED.value in phases
    ), f"Z-7: 未进入 CONTEXT_COLLECTED——观测闭环没被走到，phases={phases}"
    assert "observation" in types, f"Z-7: 无 observation 事件，types={types}"
    assert State.PLAN_GENERATED.value in phases, "Z-7: 观测后未进入二次规划"
    assert end is State.FINISHED, f"Z-7: 未抵达终态，实际 {end}"


def test_z6_unrelated_text_still_returns_none() -> None:
    """Z-6: 无关文本仍返回 None——防"中文一律判 disk_full"式的过宽实现。

    没有这条，把中文分支写成"含任意中文即 disk_full"也能让 Z-3 全绿。
    """
    for phrase in ("你好", "介绍一下这个系统", "谢谢"):
        assert (
            _infer_problem_type_from_intent(phrase) is None
        ), f"Z-6: {phrase!r} 不该被推断成任何故障场景"
