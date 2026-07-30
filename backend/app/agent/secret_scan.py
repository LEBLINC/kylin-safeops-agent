"""C4（阶段6 第二梯队）：LLM 自然语言总结发前端前的输出侧确定性凭据扫描。

H9 窄缺口：输入侧（_sanitize_for_summary S9 浅过滤 tool_results dict 字段）+
GUARD_PROMPT 定界 + detect_tool_output_injection 注入扫描均已闭合；仅输出侧缺
确定性兜底——summary 是 LLM **生成**的自由文本，即便输入已过滤，LLM 仍可能
（幻觉/复述残留）在输出里带出凭据模式。本模块在 summary 发前端 SSE 前再扫一遍，
命中 → redact，让 orchestrator.py 里恒 False 的 sensitive_filtered 死标志变活。

放在 agent/ 而非 security/：本工单 C3 边界不含 backend/app/security（相邻但非
本工单授权改动范围）；纯正则扫描零外部依赖，放调用方（orchestrator）同域最小化改动面。
"""

from __future__ import annotations

import re

#: 凭据模式（与 audit_logger.SqliteAuditSink._SENSITIVE_KEYS /
#: real_client.RealLLMClient._SENSITIVE_KEYS 同口径的 6 类 key 名，
#: 扩展为可匹配自由文本里 "key_name: value" / "key_name=value" 形态）。
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bind[_-]?password|secret|token|password)\b" r"\s*[:=]\s*\S+"
)


def scan_and_redact(text: str) -> tuple[str, bool]:
    """扫描 text 中的凭据模式，命中则替换为 ``<key>: ***REDACTED***``。

    返回 (处理后文本, 是否命中)。未命中原样返回 (text, False)，
    调用方据此设置 StreamEvent.data.sensitive_filtered。
    """
    if not text:
        return text, False
    hit = False

    def _replace(m: re.Match[str]) -> str:
        nonlocal hit
        hit = True
        return f"{m.group(1)}: ***REDACTED***"

    redacted = _CREDENTIAL_PATTERN.sub(_replace, text)
    return redacted, hit
