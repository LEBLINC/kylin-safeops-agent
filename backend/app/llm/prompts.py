"""LLM 规划阶段的强约束提示词（手册 §3.2 / 契约2 约束）。

核心安全约束（对应铁律 1/3）：LLM 是"不可信顾问"，只能产出
「工具名 + 结构化参数 + 理由」的 JSON（契约2 Intent），绝不生成或执行裸 shell。
"""

from __future__ import annotations

import json

from backend.app.contracts.intent import Intent

# 规划阶段 system prompt 主体。运行时通过 build_system_prompt() 注入 Intent JSON Schema。
_SYSTEM_PROMPT_HEAD = """\
你是麒麟安全运维 Agent 的规划器，被视为"不可信顾问"。你的唯一职责是把用户意图
转成结构化的工具调用计划，交由确定性的策略引擎与特权代理去执行。

强制规则（违反任意一条都会被下游拒绝）：
1. 只能输出一个 JSON 对象，不要输出任何额外文字、解释或 Markdown 代码块标记。
2. 绝不生成、拼接或建议任何 shell 命令、脚本、管道或裸命令字符串。
3. 你只能从"可用工具清单"里选择工具，按其 input_schema 填写结构化参数 (args)。
   不得发明工具名，不得在 args 里塞命令字符串或任意路径以外的危险字段。
4. 若信息不足以安全规划，应将 need_observation 设为 true 并优先选择只读观测工具。
5. risk_hint 仅为你的主观提示，最终风险与放行由策略引擎裁决，不由你决定执行。

输出必须严格符合下面的 JSON Schema："""

# 降级语义：当 LLM 输出始终无法解析为合法 Intent 时，回退为"仅观测、不规划"。
OBSERVE_ONLY_INTENT = Intent(
    intent="observe_only",
    confidence=0.0,
    need_observation=True,
    candidate_tools=[],
    risk_hint="low",
    justification="LLM 输出无法解析为合法 Intent，降级为仅观测、不规划。",
)


def build_system_prompt() -> str:
    """构造规划 system prompt，附 Intent 的 JSON Schema。"""
    schema = json.dumps(Intent.model_json_schema(), ensure_ascii=False, indent=2)
    return f"{_SYSTEM_PROMPT_HEAD}\n{schema}"


def build_repair_prompt(raw_output: str, error: str) -> str:
    """构造纠错提示：把上一次的坏输出与校验错误回喂给模型，要求自修。"""
    return (
        "你上一次的输出无法解析为合法的 Intent JSON。\n"
        f"上一次输出：\n{raw_output}\n\n"
        f"校验错误：\n{error}\n\n"
        "请只输出修正后的、严格符合 Intent JSON Schema 的单个 JSON 对象，不要任何额外文字。"
    )
