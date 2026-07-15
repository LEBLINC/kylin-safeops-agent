"""联调注入桩集中地（待 D/X 真实现替换）。

本文件所有内容均为【注入桩 / fake】，仅用于联调与空跑。

═══════════════════════════════════════════════════════════════════
注入点替换清单（接线状态留痕）
═══════════════════════════════════════════════════════════════════
三个协作者件，真实现均归 D（C3 越界红线：L 侧不实现 evaluate/execute/append）：

  ① PolicyEngine（策略裁决）✅ 已切真
     现状：build_gateway() 已注入 D 的真 PolicyEngine(DEFAULT_POLICY, registry)。
     桩 FakePolicyEngine 保留供测试按需注入 allow-all 场景。

  ② Executor（特权代理执行）✅ 已切真
     现状：build_gateway() 已注入 D 的真 PrivilegeExecutor（无参构造）。
     桩 FakeExecutor 保留供测试按需注入（dependency_overrides）成功罐头场景。

  ③ AuditSink（哈希链审计落库）✅ 已切真
     现状：app.get_audit() 返回 lifespan 单例 SqliteAuditSink（持 DB 句柄+链状态）。
     桩 FakeAudit 保留供测试无落库场景。

另含 LLM 注入桩（待接真实 LLM 端点，非 D 模块）：
     桩：build_fake_llm（本文件）；接线处：app.get_llm() provider。

装配点：app.py 的 build_gateway / get_audit / get_llm 三个 provider。
config.diff 已在 mcp 层聚合接回 registry（决策⑤，见 _DEFERRED_TOOLS / config_diff 模块）。
═══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re

from backend.app.contracts.audit import AuditRecord
from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.policy import PolicyVerdict
from backend.app.contracts.untrusted import ToolResult
from backend.app.executor import PrivilegeExecutor
from backend.app.llm.adapter import LLMAdapter, Message
from backend.app.mcp.gateway import MCPGateway
from backend.app.mcp.registry import ToolRegistry
from backend.app.security import DEFAULT_POLICY, PolicyEngine
from mcp_servers.os_ops import all_specs

logger = logging.getLogger(__name__)

#: 沙箱启用 env 开关名（值为 "1" 且平台非 Windows 才生效；默认关）。
_SANDBOX_ENV = "KYLIN_SANDBOX_ENABLED"

#: app 注册集中暂缓注册的工具（L 域 registry 装配过滤，不碰 os_ops 工具声明本身）。
#: config.diff 已由 L 在 mcp 层聚合接回（决策⑤，见 backend/app/mcp/config_diff.py +
#: gateway._aggregate_config_diff）——故不再在此摘除，registry/`/api/tools/registry` 重新含它。
#: 本集合保留为空 + 过滤机制（future-proof：若再有"无单命令模板需 mcp 层特判"的工具可在此暂缓）。
_DEFERRED_TOOLS: set[str] = set()


class FakePolicyEngine:
    """注入桩：永远 allow。

    注：默认 app 装配已切换为 D 的真 PolicyEngine（见 build_gateway）；
    本桩保留供测试按需注入（dependency_overrides）构造 allow-all 场景。
    """

    def evaluate(self, tool: CandidateTool) -> PolicyVerdict:
        return PolicyVerdict(
            decision="allow",
            final_risk="R0",
            matched_rules=[],
            reason="fake policy: allow all",
            approval_required=False,
        )


class FakeExecutor:
    """注入桩：永远返回成功空结果。app 已切真 PrivilegeExecutor；本桩仅供测试注入。"""

    async def execute(self, tool: CandidateTool) -> ToolResult:
        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=0,
            stdout_truncated="[fake] executed successfully",
            is_untrusted=True,
        )


class FakeAudit:
    """注入桩：审计落库空操作。app 已切真 SqliteAuditSink 单例；本桩仅供测试无落库场景。"""

    def append(self, record: AuditRecord) -> None:
        return None


def build_fake_audit() -> FakeAudit:
    """装配 fake AuditSink（注入桩，仅供测试；app 已用真 SqliteAuditSink 单例）。"""
    return FakeAudit()


def build_gateway() -> MCPGateway:
    """装配默认 MCPGateway：【真 registry + 真策略 + 真特权执行器】。

    现状（全真，config.diff 经 mcp 层聚合接回）：
    - registry：真 os_ops 工具集 all_specs()（_DEFERRED_TOOLS 现为空，全量注册含 config.diff）。
    - policy：D 的真 PolicyEngine(DEFAULT_POLICY, registry)——同一 registry 实例防漂移。
    - executor：D 的真 PrivilegeExecutor，sandbox_enabled 按平台 + env 接通（见下）。

    沙箱启用（L 仅接"开关"，不碰 executor/sandbox 实现）：
    - sandbox_enabled = (非 Windows) 且 env KYLIN_SANDBOX_ENABLED=="1"；
    - **默认关**（未设 env 或 Windows → False → 零行为改变、现有测试零回归）；
    - 仅 Linux + 显式 KYLIN_SANDBOX_ENABLED=1 才开（麒麟部署由 systemd unit/env 设），
      开时命令经 wrapper 跑 systemd 瞬态 service（D 的实现）。

    切真后运行中的 app 会经特权代理跑真命令（方案B：失败用 exit_code 承载，仅系统级故障 raise）。
    LLM/审计经各自 provider（get_llm/get_audit）注入，不在本装配点。
    config.diff 经 gateway 三道闸后在 mcp 层聚合（决策⑤，见 config_diff 模块），不落 D 执行器。
    """
    specs = [s for s in all_specs() if s.name not in _DEFERRED_TOOLS]
    registry = ToolRegistry(specs)
    sandbox_enabled = (
        platform.system() != "Windows" and os.environ.get(_SANDBOX_ENV, "").strip() == "1"
    )
    if sandbox_enabled:
        logger.info("沙箱已启用（systemd 瞬态 service，KYLIN_SANDBOX_ENABLED=1）")
    else:
        logger.info("沙箱默认关闭（零行为改变）；生产需 Linux + KYLIN_SANDBOX_ENABLED=1 才启用")
    return MCPGateway(
        registry=registry,
        policy=PolicyEngine(DEFAULT_POLICY, registry),
        executor=PrivilegeExecutor(sandbox_enabled=sandbox_enabled),  # type: ignore[arg-type]
    )


# 默认 fake 意图：提议真只读工具 system.info（R0）——真策略下 allow→执行→verified。
_FAKE_INTENT_JSON = json.dumps(
    {
        "intent": "system_info",
        "confidence": 0.9,
        "need_observation": False,
        "candidate_tools": [{"name": "system.info", "args": {}}],
        "risk_hint": "low",
        "justification": "查看系统基本信息（fake 规划）",
    }
)

# confirm 计划样例（任务丁）：让 fake planner 能产 WAIT_APPROVAL 链，解 X 审批联调阻塞。
# 字段照契约：candidate_tools[].name 是 CandidateTool 字段（绝不可改成 tool）；args 须过 gate2。
_FAKE_INTENT_RESTART = json.dumps(
    {
        "intent": "service_restart",
        "confidence": 0.9,
        "need_observation": False,
        "candidate_tools": [{"name": "service.restart", "args": {"service_name": "nginx.service"}}],
        "risk_hint": "high",
        "justification": "重启服务（fake 规划，R3→confirm/admin）",
    }
)
_FAKE_INTENT_ROTATE = json.dumps(
    {
        "intent": "log_compress_rotate",
        "confidence": 0.9,
        "need_observation": False,
        "candidate_tools": [{"name": "log.compress_rotate", "args": {"path": "/var/log/app.log"}}],
        "risk_hint": "medium",
        "justification": "压缩轮转日志（fake 规划，R2→confirm/operator）",
    }
)

# 关键词 → 意图 JSON（命中顺序：restart 优先于 rotate）。
_RESTART_KEYWORDS = ("重启", "restart")
_ROTATE_KEYWORDS = ("压缩", "轮转", "rotate", "清日志", "清理日志")
_LOOKUP_KEYWORDS = ("查", "查询", "lsof", "看", "看哪些进程在用")  # file.lsof_check 路径
_DISK_KEYWORDS = ("查看磁盘", "磁盘占用", "disk")  # disk.usage

# service_name 提取：取首个空白分词后、直到结尾或下一个非字母数字字符
_SERVICE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]*")
# path 提取：取首个 ^/... 形式的绝对路径
_PATH_RE = re.compile(r"(/[A-Za-z0-9._/@-]+)")


def _parse_service_name(content: str) -> str | None:
    """从 `重启 <name>` / `restart <name>` 后的 token 里提取 service_name。

    无 service_name（仅说"重启"）→ None（fallback：默认 cron.service 兜底，
    与 demo `scenario_c(target_service=)` 默认值一致）。
    """
    for kw in _RESTART_KEYWORDS:
        idx = content.find(kw)
        if idx < 0:
            continue
        tail = content[idx + len(kw) :].strip()
        # 跳过常见语气词
        for filler in ("一下", "下", "服务", "服务吧", "吧", "服务下", "，", "。", ","):
            if tail.startswith(filler):
                tail = tail[len(filler) :].strip()
        m = _SERVICE_NAME_RE.match(tail)
        if m:
            token = m.group(0)
            # 若不含 .service/.socket 等后缀且纯字母数字 → 自动补 .service（Linux systemd 习惯）
            if "." not in token and "_" not in token and "-" not in token:
                return f"{token}.service"
            return token
    return None


def _parse_path(content: str) -> str | None:
    """从 message 里提取首个以 / 开头的绝对路径（不引入 NLP，CI 友好）。"""
    m = _PATH_RE.search(content)
    return m.group(1) if m else None


def _last_user_content(messages: list[Message]) -> str:
    """取最后一条 user 消息正文（fake planner 按它选意图）。"""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content", ""))
    return ""


async def _fake_summary_fn(
    tool_results: list[dict],
    user_intent: str,
    *,
    evidence: list[dict] | None = None,
    structured_report: dict | None = None,
) -> str | None:
    """fake 自然语言总结（确定性，CI 友好，async 与 LLMAdapter.SummaryFn 契约一致）。

    输出 "已完成:<tool_names>"（与 LLMAdapter._default_summary_fn 同款），
    之所以单独存在是为了让 _fakes.build_fake_llm 的语义显式："fake 桩对外可见
    的 summarize 行为是固定的"，便于测试断言。async 包装是为了适配
    backend.app.llm.adapter.SummaryFn 的 Awaitable[str | None] 类型别名，
    即便内部不需要 IO 也走 await；真 LLM.summarize 同样签名。
    RCA P4：evidence/structured_report 本桩不使用，接受仅为签名一致（不 raise）。
    """
    if not tool_results:
        return "已完成:（无工具结果）"
    names = sorted({str(r.get("tool", "?")) for r in tool_results if isinstance(r, dict)})
    return f"已完成:{','.join(names)}"


def _intent_for_message(content: str) -> str:
    """按关键词选 fake 意图（不再写死 service_name/path；解析 user message 提取）。

    解析规则（CI 友好，不引入 NLP）：
    - 含"重启/restart" → service.restart (R3 confirm/admin)，service_name 从 message 提取
      （"重启 sshd" → sshd.service；"重启 cron.service" → cron.service；
      仅"重启" → 默认 cron.service——保留 fallback 与 demo 默认兼容）
    - 含"压缩/轮转/rotate/清日志" → log.compress_rotate (R2 confirm/operator)，
      path 从 message 提取（"压缩 /var/log/app.log" → /var/log/app.log；
      无 path → 默认 /var/log/app.log——保留 fallback 与 demo 默认兼容）
    - 含"查/查询/lsof" + 路径 → file.lsof_check (R0 allow)
    - 含"查看磁盘/磁盘占用" → disk.usage (R0 allow)
    - 其它 → system.info (R0 allow，默认）
    """
    if any(kw in content for kw in _RESTART_KEYWORDS):
        svc = _parse_service_name(content) or "cron.service"
        return json.dumps(
            {
                "intent": "service_restart",
                "confidence": 0.9,
                "need_observation": False,
                "candidate_tools": [{"name": "service.restart", "args": {"service_name": svc}}],
                "risk_hint": "high",
                "justification": f"重启 {svc}（fake 规划，R3→confirm/admin）",
            }
        )
    if any(kw in content for kw in _ROTATE_KEYWORDS):
        path = _parse_path(content) or "/var/log/app.log"
        return json.dumps(
            {
                "intent": "log_compress_rotate",
                "confidence": 0.9,
                "need_observation": False,
                "candidate_tools": [{"name": "log.compress_rotate", "args": {"path": path}}],
                "risk_hint": "medium",
                "justification": f"压缩轮转 {path}（fake 规划，R2→confirm/operator）",
            }
        )
    if any(kw in content for kw in _LOOKUP_KEYWORDS):
        lsof_path = _parse_path(content)
        if lsof_path is not None:
            return json.dumps(
                {
                    "intent": "check_open_files",
                    "confidence": 0.9,
                    "need_observation": False,
                    "candidate_tools": [{"name": "file.lsof_check", "args": {"path": lsof_path}}],
                    "risk_hint": "low",
                    "justification": f"lsof {lsof_path}（fake 规划，R0 allow）",
                }
            )
    if any(kw in content for kw in _DISK_KEYWORDS):
        return json.dumps(
            {
                "intent": "disk_usage",
                "confidence": 0.9,
                "need_observation": False,
                "candidate_tools": [{"name": "disk.usage", "args": {}}],
                "risk_hint": "low",
                "justification": "查看磁盘占用（fake 规划，R0 allow）",
            }
        )
    return _FAKE_INTENT_JSON


def build_fake_llm(intent_json: str | None = None) -> LLMAdapter:
    """装配 fake LLMAdapter（注入桩，不联网，待接真实 LLM 端点替换）。

    - 显式传 intent_json：completion_fn 永远返回它（测试用固定意图）。
    - 不传：按最后一条 user 消息关键词选意图（任务丁）——含"重启/restart"→ service.restart(R3,
      confirm/admin）；含"压缩/轮转/rotate/清日志"→ log.compress_rotate(R2, confirm/operator)；
      其它 → system.info(R0, allow)。使状态机能真实进 WAIT_APPROVAL，解 X 审批联调阻塞。
    - summary_fn：固定 _fake_summary_fn → "已完成:<tool_names>"；真 LLM 由
      D VM 在 D-side 接入后改 RealLLMClient.summarize_fn 注入本 LLMAdapter。
    """
    if intent_json is not None:
        payload = intent_json

        async def _fixed_completion(messages: list[Message]) -> str:
            return payload

        return LLMAdapter(completion_fn=_fixed_completion, summary_fn=_fake_summary_fn)

    async def _keyword_completion(messages: list[Message]) -> str:
        return _intent_for_message(_last_user_content(messages))

    return LLMAdapter(completion_fn=_keyword_completion, summary_fn=_fake_summary_fn)
