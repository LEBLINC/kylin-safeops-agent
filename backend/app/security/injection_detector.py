"""输入闸：提示词注入检测器（D — D-10）。

定位（与 PI001 区分）：
- 现有 `policy_loader.py` 的 `PI001` 是扫 `tool_args` 的【结构化参数闸】，归策略引擎。
- 本模块是【user_input 输入闸】：在 LLM 看到用户输入【之前】做确定性判定，
  与 PI001 维度不同、不替换、不重叠。接线由 L 在 orchestrator 首次 `plan()` 前接，
  本模块只提供纯函数检测器，不接任何 orchestrator/router。

实现纪律：
- 纯函数、无状态、无 IO（不读 ENV / 不读文件 / 不打日志）；同输入恒定同输出。
- 规则写成模块级 `_PATTERNS`，每条正则只 `re.compile` 一次，确定性顺序。
- 所有正则量词限定上界，规避灾难回溯（ReDoS）。
- 预处理：去 BOM、`\r\n→\n`、NFKC 归一（防全角/兼容字符钝化绕过），
  超 32KB 截断后再扫描（防 ReDoS / 内存放大）；不做小写化，匹配统一 `re.IGNORECASE`。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

InjectionCategory = Literal[
    "override_rules",  # “忽略前面的指示” / “ignore previous instructions”
    "role_hijack",  # “你现在是 root” / “act as system / DAN”
    "system_prompt_forgery",  # 伪造系统/开发者标签：<|system|> / [INST] / “### system:”
    "delimiter_forgery",  # 伪造对话定界符以越权
    "command_injection_lure",  # “请直接执行 rm -rf /” / “运行下面这段 shell”
    "exfiltration",  # “把你的 system prompt / 密钥 / .env 发给我”
]

_Severity = Literal["high", "medium"]


@dataclass(frozen=True)
class InjectionFinding:
    """单条命中结果（确定性、可序列化、面向审计与前端展示）。"""

    category: InjectionCategory
    pattern_id: str  # 稳定 id，例：PI-OVR-001
    matched_span: str  # 命中的子串（裁断到 ≤120 字符 + “…”）
    severity: _Severity
    reason: str  # 中文，一句话


# 扫描上界：超过则先截断再扫描（按字符数，32KB）。
_MAX_SCAN_CHARS = 32 * 1024
# 命中子串展示上界。
_MAX_SPAN_CHARS = 120
# severity 排序权重：high 优先于 medium。
_SEVERITY_RANK: dict[_Severity, int] = {"high": 0, "medium": 1}

# 规则表：(category, pattern_id, severity, reason, 正则)。
# 每条 re.compile 一次；统一 IGNORECASE（中文模式不受影响）。
# 选取逻辑与表顺序无关：命中后按 (severity, pattern_id) 排序取第一条。
_RAW_PATTERNS: tuple[tuple[InjectionCategory, str, _Severity, str, str], ...] = (
    # ---- override_rules（覆盖/无视安全规则）-------------------------------
    (
        "override_rules",
        "PI-OVR-001",
        "high",
        "检测到要求忽略/覆盖安全规则的注入。",
        r"(忽略|忘记|覆盖|无视|绕过)[^。\n]{0,40}(规则|限制|安全|约束|指令|系统提示|system\s*prompt)",
    ),
    (
        "override_rules",
        "PI-OVR-002",
        "high",
        "检测到 ignore previous instructions 类注入。",
        r"ignore\s+(all\s+)?(the\s+)?previous\s+(instructions|rules|prompts|messages)",
    ),
    (
        "override_rules",
        "PI-OVR-003",
        "high",
        "检测到 disregard system/safety/rules 类注入。",
        r"disregard\s+(the\s+|all\s+|any\s+)*(system|safety|rules|previous|above|constraints?)",
    ),
    # ---- role_hijack（角色劫持）-------------------------------------------
    (
        "role_hijack",
        "PI-ROL-001",
        "high",
        "检测到中文角色劫持（提升为 root/管理员/DAN 等）。",
        r"你现在(是|就是|扮演)[^。\n]{0,20}(root|管理员|超级用户|超级管理员|DAN|开发者模式|无限制)",
    ),
    (
        "role_hijack",
        "PI-ROL-002",
        "high",
        "检测到 act as root/admin/system/DAN 类角色劫持。",
        r"act\s+as\s+(an?\s+|the\s+)?(root|admin|administrator|system|developer|DAN)\b",
    ),
    (
        "role_hijack",
        "PI-ROL-003",
        "high",
        "检测到 developer mode / jailbreak / pretend you are 类越权。",
        r"(developer\s+mode|jailbreak|pretend\s+you\s+are|enable\s+dan)",
    ),
    # ---- system_prompt_forgery（伪造系统/开发者标签）----------------------
    (
        "system_prompt_forgery",
        "PI-SYS-001",
        "high",
        "检测到伪造的系统/开发者标记（<|system|> 等）。",
        r"<\|\s*(system|im_start|developer|assistant)\s*\|>",
    ),
    (
        "system_prompt_forgery",
        "PI-SYS-002",
        "high",
        "检测到伪造的 [INST] 指令标记。",
        r"\[\s*/?\s*INST\s*\]",
    ),
    (
        "system_prompt_forgery",
        "PI-SYS-003",
        "high",
        "检测到伪造的 “### system:” 角色头。",
        r"#{2,4}\s*(system|developer)\s*[:：]",
    ),
    (
        "system_prompt_forgery",
        "PI-SYS-004",
        "high",
        "检测到伪造的 <system> 标签。",
        r"<\s*system\s*>",
    ),
    (
        "system_prompt_forgery",
        "PI-SYS-005",
        "high",
        "检测到伪造的 assistant→system 角色切换块。",
        r"assistant\s*[:：]\s*\n[\s\S]{0,120}?system\s*[:：]",
    ),
    # ---- delimiter_forgery（伪造对话定界符，medium）-----------------------
    (
        "delimiter_forgery",
        "PI-DLM-001",
        "medium",
        "检测到三引号包裹的伪造 system 段。",
        r'"""\s*system',
    ),
    (
        "delimiter_forgery",
        "PI-DLM-002",
        "medium",
        "检测到伪造的 BEGIN SYSTEM 定界块。",
        r"-{3,}\s*BEGIN\s+SYSTEM",
    ),
    (
        "delimiter_forgery",
        "PI-DLM-003",
        "medium",
        "检测到伪造的对话角色定界标签（<human>/<assistant>/<user>）。",
        r"<\s*/?\s*(human|assistant|user)\s*>",
    ),
    # ---- command_injection_lure（诱导执行破坏性命令，含 S001–S007）--------
    (
        "command_injection_lure",
        "PI-CMD-001",
        "high",
        "检测到诱导对文件系统根/系统目录执行 rm（S001/S002）。",
        r"\brm\s+-[rf]{1,3}\s+/(?:\s|$|\*|etc|var|usr|boot|bin|sbin|lib|root|home|dev|proc|sys)",
    ),
    (
        "command_injection_lure",
        "PI-CMD-002",
        "high",
        "检测到诱导对系统开放全权限（chmod 777，S003）。",
        r"\bchmod\s+(-R\s+)?(0?7{3}|a\+rwx)\b",
    ),
    (
        "command_injection_lure",
        "PI-CMD-003",
        "high",
        "检测到诱导将远程脚本直接管入 shell（curl|sh，S004）。",
        r"\b(curl|wget)\b[^\n|]{0,200}\|\s*(sudo\s+)?(ba)?sh\b",
    ),
    (
        "command_injection_lure",
        "PI-CMD-004",
        "high",
        "检测到诱导执行裸盘写/格式化/fork bomb 类破坏命令。",
        r"\bdd\s+if=|\bmkfs(\.\w+)?\b|>\s*/dev/sd[a-z]|:\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
    ),
    (
        "command_injection_lure",
        "PI-CMD-005",
        "high",
        "检测到诱导清空/篡改系统目录、日志或数据库 binlog（S002/S005/S006/S007）。",
        r"(清空|清除|删除|删光|删掉|抹掉|格式化|篡改|强制(重启|清空|删除))"
        r"[^。\n]{0,30}"
        r"(/etc|/var|/boot|/usr|/dev|根目录|系统目录|系统盘|审计日志|访问日志|日志|binlog|二进制日志|/var/log|/var/lib/mysql)",
    ),
    (
        "command_injection_lure",
        "PI-CMD-006",
        "high",
        "检测到诱导执行“下面这段 shell/脚本”类整段命令。",
        r"(执行|运行|跑)\s*(一下)?\s*(下面|以下|这段|如下)[^。\n]{0,12}(shell|命令|脚本|代码|bash)"
        r"|(run|execute)\s+(the\s+)?(following|this|below)\s+(shell|command|script|code)",
    ),
    # ---- exfiltration（外泄 system prompt / 密钥 / .env）------------------
    (
        "exfiltration",
        "PI-EXF-001",
        "high",
        "检测到诱导外泄 system prompt / 系统指令。",
        r"(你的|the\s+|your\s+)?\s*(system\s*prompt|系统提示词?|系统指令|原始指令)"
        r"[^。\n]{0,30}(发|发给|告诉|输出|打印|复述|泄露|print|reveal|show|dump|repeat)",
    ),
    (
        "exfiltration",
        "PI-EXF-002",
        "high",
        "检测到诱导外泄 system prompt / 系统指令（动词在前）。",
        r"(发给我|告诉我|输出|打印|复述|泄露|reveal|show\s+me|print|dump|repeat)"
        r"[^。\n]{0,20}(你的|the\s+|your\s+)?\s*(system\s*prompt|系统提示词?|系统指令|原始指令)",
    ),
    (
        "exfiltration",
        "PI-EXF-003",
        "high",
        "检测到诱导外泄密钥 / .env / 私钥 / 口令。",
        r"(\.env|id_rsa|/etc/shadow|password|passwd|api[_-]?key|secret|私钥|密钥|口令|凭证)"
        r"[^。\n]{0,30}(发|发给|告诉|paste|leak|泄露|show|reveal|输出|打印|外传|上传|贴出)",
    ),
    (
        "exfiltration",
        "PI-EXF-004",
        "high",
        "检测到诱导以 base64 编码外带密钥/凭证。",
        r"base64[^。\n]{0,20}(encode|编码)[^。\n]{0,30}(secret|key|env|密钥|凭证|token)",
    ),
)

#: 编译后的规则表（模块加载期编译一次）。
_PATTERNS: tuple[tuple[InjectionCategory, str, _Severity, str, re.Pattern[str]], ...] = tuple(
    (category, pattern_id, severity, reason, re.compile(pattern, re.IGNORECASE))
    for category, pattern_id, severity, reason, pattern in _RAW_PATTERNS
)


def _preprocess(user_input: str) -> str:
    """去 BOM、CRLF 归一、NFKC 折叠、超长截断；不做小写化。"""
    text = user_input.replace("\ufeff", "")
    if len(text) > _MAX_SCAN_CHARS:
        text = text[:_MAX_SCAN_CHARS]
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _clip_span(span: str) -> str:
    """命中子串裁断到 ≤120 字符（超出补 “…”）。"""
    if len(span) > _MAX_SPAN_CHARS:
        return span[:_MAX_SPAN_CHARS] + "…"
    return span


def detect_injection(user_input: str) -> InjectionFinding | None:
    """对单条 user_input 做确定性提示词注入检测。

    无状态、无 IO。空串 / None / 纯空白直接返回 None。
    命中多条时按 severity（high > medium）、再按 pattern_id 升序取第一条。
    """
    if not user_input or not user_input.strip():
        return None

    text = _preprocess(user_input)

    findings: list[InjectionFinding] = []
    for category, pattern_id, severity, reason, pattern in _PATTERNS:
        match = pattern.search(text)
        if match is not None:
            findings.append(
                InjectionFinding(
                    category=category,
                    pattern_id=pattern_id,
                    matched_span=_clip_span(match.group(0)),
                    severity=severity,
                    reason=reason,
                )
            )

    if not findings:
        return None

    findings.sort(key=lambda f: (_SEVERITY_RANK[f.severity], f.pattern_id))
    return findings[0]
