"""O18 修复回归：planner prompt 注入可用工具清单 + few-shot 不再毒。

D 在 VM 真端点首跑暴露：qwen3-max "查看磁盘占用" → disk.usage 幻觉 path → 闸2
拦死。根因 = prompt 喂了 Intent 信封 schema 但**没喂工具清单** + few-shot 给
disk.usage（无参工具）塞了 path。

本文件固化 L 域修复：
- build_system_prompt(specs=...) 注入"可用工具清单 + 各自 input_schema"
- few-shot 改：disk.usage 用空 args + disk.large_files 演示"按 schema 填参"
- LLMAdapter(tool_specs=...) 在 plan() 时把工具清单带进 system prompt
- 不联网回归：fixture 模式场景 G 仍跑通
"""

from __future__ import annotations

import asyncio
import re

from backend.app.llm.adapter import LLMAdapter, LLMConfig
from backend.app.llm.prompts import build_system_prompt
from backend.app.llm.real_client import (
    _fixture_intent_for_message,
)
from mcp_servers.os_ops import all_specs

# ---- 1. prompt 注入工具清单（不联网，CI 友好）-----------------------------


def test_prompt_includes_tool_catalog_when_specs_provided() -> None:
    """build_system_prompt(specs=...) 必须输出可用工具清单。

    至少：每个 spec 的 name / risk / input_schema 字段都被渲染。
    """
    p = build_system_prompt(all_specs())
    assert "可用工具清单" in p
    # 至少 disk.usage 与 log.compress_rotate 都被列出
    assert "disk.usage" in p
    assert "log.compress_rotate" in p
    assert "service.restart" in p


def test_prompt_marks_disk_usage_as_argless_in_catalog() -> None:
    """O18 核心断言：disk.usage 工具清单里必须显示**无参**（properties 空）。"""
    p = build_system_prompt(all_specs())
    # 截取 disk.usage 所在的工具块
    m = re.search(r"- disk\.usage.*?(?=\n- |\Z)", p, re.DOTALL)
    assert m is not None, "工具清单里没找到 disk.usage 块"
    block = m.group(0)
    # properties 必须为空 + additionalProperties:false（明确禁止塞 path）
    assert '"properties": {}' in block
    assert '"additionalProperties": false' in block


def test_prompt_marks_log_compress_rotate_args_required() -> None:
    """对照：log.compress_rotate 标注有 path 必填——LLM 知道哪些工具真有参。"""
    p = build_system_prompt(all_specs())
    m = re.search(r"- log\.compress_rotate.*?(?=\n- |\Z)", p, re.DOTALL)
    assert m is not None
    block = m.group(0)
    assert '"path"' in block
    assert '"required"' in block


def test_fewshot_disk_usage_no_longer_pollutes_path() -> None:
    """O18 第二根因：few-shot 里 disk.usage 绝不能再塞 path。"""
    p = build_system_prompt(all_specs())
    # few-shot 区段（FEWSHOT_EXAMPLE 整段）
    fewshot_idx = p.find("合法输出示例")
    assert fewshot_idx >= 0
    fewshot = p[fewshot_idx:]
    # 截取无参工具的范例——必须 args 为空
    m = re.search(r'\{"name": "disk\.usage", "args": \{(.*?)\}', fewshot)
    assert m is not None, "few-shot 缺无参工具范例"
    assert (
        m.group(1).strip() == ""
    ), f"few-shot 给 disk.usage 塞了参数：{m.group(0)!r}——会教坏真 LLM"


def test_fewshot_shows_parametrized_tool_correctly() -> None:
    """few-shot 第二段：disk.large_files(path=/var/log) 演示按 schema 填参。"""
    p = build_system_prompt(all_specs())
    fewshot = p[p.find("合法输出示例") :]
    assert '"name": "disk.large_files"' in fewshot
    assert '"path": "/var/log"' in fewshot


def test_prompt_without_specs_keeps_legacy_behavior() -> None:
    """specs=None 时退化旧行为（仅信封 schema），fixture/旧测试兼容。"""
    p = build_system_prompt(None)
    section_marker = "- disk.usage"  # 实际工具清单节特征
    assert (
        section_marker not in p
    ), "specs=None 应跳过实际工具清单节（section header），但 prompt 仍包含它"
    # 仍含 Intent 信封 schema
    assert '"properties"' in p  # JSON Schema 渲染
    # 仍含 few-shot
    assert "合法输出示例" in p


# ---- 2. LLMAdapter(tool_specs=...) 把清单带进 plan() 的 system prompt -------


def test_llm_adapter_uses_tool_specs_in_plan_prompt() -> None:
    """LLMAdapter(tool_specs=...) 实例化后调 plan()，spy 完成函数拿到含工具清单的 system prompt。"""
    captured: dict = {}

    async def spy_completion(messages: list[dict[str, str]]) -> str:
        # 抓首条 system message
        captured["system"] = messages[0]["content"]
        # 返 fixture 路径的合法 intent（disk.usage 无参）
        return _fixture_intent_for_message("查看磁盘")

    adapter = LLMAdapter(completion_fn=spy_completion, tool_specs=all_specs())
    asyncio.run(adapter.plan([{"role": "user", "content": "查看磁盘"}]))

    sys_msg = captured["system"]
    assert "可用工具清单" in sys_msg
    assert "disk.usage" in sys_msg


def test_llm_adapter_retry_prompt_also_includes_catalog() -> None:
    """plan() 重试时 system prompt 仍含工具清单（LLM 在 repair 轮也能改对参数）。"""
    captured: list[str] = []

    async def bad_first_good_second(messages: list[dict[str, str]]) -> str:
        captured.append(messages[0]["content"])
        if len(captured) == 1:
            return "{bad json"  # 触发重试
        return _fixture_intent_for_message("查看磁盘")

    adapter = LLMAdapter(
        completion_fn=bad_first_good_second, tool_specs=all_specs(), config=LLMConfig(max_retries=2)
    )
    asyncio.run(adapter.plan([{"role": "user", "content": "查看磁盘"}]))

    # 两轮 system prompt 都含工具清单
    assert len(captured) >= 2
    for s in captured:
        assert "可用工具清单" in s


# ---- 3. 不联网 fixture 模式场景 G 仍跑通（回归）--------------------------


def test_scenario_g_fixture_still_works() -> None:
    """修复不破 fixture 模式：scenario_real(user_intent="查看磁盘占用情况") 仍 FINISHED。

    fixture 关键词路由不依赖 prompt 工具清单——但本测试确保 LLMAdapter 装配
    tool_specs 不影响 fixture 行为。
    """
    from scripts.demo_stage4_common import build_e2e

    async def scenario() -> dict:
        orch, evs, audit, sink = build_e2e(trace_id="o18-regress", use_real_llm=True)
        state = await orch.run(
            [{"role": "user", "content": "查看磁盘占用情况"}],
            user_intent="查看磁盘占用情况",
        )
        return {"state": state.value, "verify": sink.verify_chain("o18-regress").valid}

    result = asyncio.run(scenario())
    assert result["state"] == "FINISHED"
    assert result["verify"] is True
