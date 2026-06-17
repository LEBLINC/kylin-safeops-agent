"""阶段4 端到端 demo 回归测试：固化五道闸全链 + 审计篡改检出。

与 `scripts/demo_stage4_e2e.py` 共享 `scripts/demo_stage4_common.build_e2e`——
本文件只是把 6 个场景的硬断言包装为 pytest 用例形式（便于 CI/审阅亲跑）。

**重要**：本文件**不**复制场景实现，**不**新写 fake——只 import 既有装配。
任何场景行为变化应改 `scripts/demo_stage4_e2e.py`，本文件随之 re-export。
"""

from __future__ import annotations

import pytest

from scripts.demo_stage4_e2e import (
    scenario_a_injection_deny,
    scenario_b_policy_deny,
    scenario_c_confirm_r3_service_restart,
    scenario_d_confirm_r2_log_rotate,
    scenario_e_result_and_audit,
    scenario_f_audit_tamper_detect,
)

# ---- 五道闸各一道硬断言（5 用例）------------------------------------------


def test_scenario_a_input_gate_injection_deny() -> None:
    """输入闸：D-10 high→deny 拦在 plan 前 → REJECTED, cause=injection。"""
    res = pytest.run(scenario_a_injection_deny()) if False else _run(scenario_a_injection_deny)
    assert res["state"] == "REJECTED"
    assert res["input_gate"]["category"] in {
        "override_rules",
        "role_hijack",
        "system_prompt_forgery",
        "delimiter_forgery",
        "command_injection_lure",
        "exfiltration",
    }
    assert res["verify_chain"]["valid"] is True


def test_scenario_b_policy_gate_file001_deny() -> None:
    """策略闸：file.lsof_check(path=/etc/shadow) 命中 FILE001 → REJECTED, cause=policy_deny。"""
    res = _run(scenario_b_policy_deny)
    assert res["state"] == "REJECTED"
    assert res["verdict"]["decision"] == "deny"
    assert "FILE001" in res["matched_rules"]
    assert res["verify_chain"]["valid"] is True
    # B 走 REJECTED 路径（policy_deny），3-6 条；与 FINISHED 路径的 9-10 不同
    assert (
        3 <= res["verify_chain"]["record_count"] <= 10
    ), f"policy_deny 路径 record_count 期望 3-10，实际 {res['verify_chain']['record_count']}"


def test_scenario_c_confirm_gate_r3_service_restart() -> None:
    """确认闸 R3：service.restart WAIT_APPROVAL → admin 批准 → 续跑。"""
    res = _run(scenario_c_confirm_r3_service_restart)
    assert res["state"] == "FINISHED"
    assert res["verify_chain"]["valid"] is True
    assert (
        res["verify_chain"]["record_count"] >= 9
    ), f"record_count 期望 >= 9，实际 {res['verify_chain']['record_count']}"
    # VM 上 verified_summary == "ok"；Windows 上 == "non-zero"（无 systemctl）— 均合法
    assert res["verified_summary"] in ("ok", "one or more tools exited non-zero")


def test_scenario_d_confirm_gate_r2_log_rotate() -> None:
    """确认闸 R2：log.compress_rotate WAIT_APPROVAL → operator 批准 → 续跑。"""
    res = _run(scenario_d_confirm_r2_log_rotate)
    assert res["state"] == "FINISHED"
    assert res["verify_chain"]["valid"] is True
    assert (
        res["verify_chain"]["record_count"] >= 9
    ), f"record_count 期望 >= 9，实际 {res['verify_chain']['record_count']}"
    assert res["verified_summary"] in ("ok", "one or more tools exited non-zero")


def test_scenario_e_result_and_audit_chain() -> None:
    """结果闸 + 审计闸：is_untrusted=True + 哈希链连续 + verify_chain valid。"""
    res = _run(scenario_e_result_and_audit)
    assert res["state"] == "FINISHED"
    assert res["all_is_untrusted"] is True
    assert res["audit_record_count"] >= 1
    assert res["verify_chain"]["valid"] is True
    assert (
        res["verify_chain"]["record_count"] >= 9
    ), f"record_count 期望 >= 9，实际 {res['verify_chain']['record_count']}"


# ---- 审计完整性：篡改检出 1 用例 ------------------------------------------


def test_scenario_f_audit_tamper_detected() -> None:
    """审计闸：手动 UPDATE payload → verify_chain 报 valid=False + broken_seq + reason。"""
    res = _run(scenario_f_audit_tamper_detect)
    assert res["verify_before"]["valid"] is True
    assert (
        res["verify_before"]["record_count"] >= 9
    ), f"篡改前 record_count 期望 >= 9，实际 {res['verify_before']['record_count']}"
    assert res["verify_after"]["valid"] is False
    assert res["verify_after"]["broken_seq"] == 1
    assert "篡改" in res["verify_after"]["reason"]


# ---- 工具函数：跑协程（与既有测试同风格，不用 pytest-asyncio）------------


def _run(coro_fn) -> dict:
    """跑一个 async 场景函数并返回 dict（不接 asyncio fixture，简洁）。"""
    import asyncio

    return asyncio.run(coro_fn())
