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
    - executor：D 的真 PrivilegeExecutor（无参构造，默认 timeout=30 + DEFAULT_POLICY）。

    切真后运行中的 app 会经特权代理跑真命令（方案B：失败用 exit_code 承载，仅系统级故障 raise）。
    LLM/审计经各自 provider（get_llm/get_audit）注入，不在本装配点。
    config.diff 经 gateway 三道闸后在 mcp 层聚合（决策⑤，见 config_diff 模块），不落 D 执行器。
    """
    specs = [s for s in all_specs() if s.name not in _DEFERRED_TOOLS]
    registry = ToolRegistry(specs)
    return MCPGateway(
        registry=registry,
        policy=PolicyEngine(DEFAULT_POLICY, registry),
        executor=PrivilegeExecutor(),  # type: ignore[arg-type]
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


def _last_user_content(messages: list[Message]) -> str:
    """取最后一条 user 消息正文（fake planner 按它选意图）。"""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content", ""))
    return ""


def _intent_for_message(content: str) -> str:
    """按关键词选 fake 意图：重启→confirm(admin)、压缩/轮转→confirm(operator)、其它→allow。"""
    if any(kw in content for kw in _RESTART_KEYWORDS):
        return _FAKE_INTENT_RESTART
    if any(kw in content for kw in _ROTATE_KEYWORDS):
        return _FAKE_INTENT_ROTATE
    return _FAKE_INTENT_JSON


def build_fake_llm(intent_json: str | None = None) -> LLMAdapter:
    """装配 fake LLMAdapter（注入桩，不联网，待接真实 LLM 端点替换）。

    - 显式传 intent_json：completion_fn 永远返回它（测试用固定意图）。
    - 不传：按最后一条 user 消息关键词选意图（任务丁）——含"重启/restart"→ service.restart(R3,
      confirm/admin)；含"压缩/轮转/rotate/清日志"→ log.compress_rotate(R2, confirm/operator)；
      其它 → system.info(R0, allow)。使状态机能真实进 WAIT_APPROVAL，解 X 审批联调阻塞。
    """
    if intent_json is not None:
        payload = intent_json

        async def _fixed_completion(messages: list[Message]) -> str:
            return payload

        return LLMAdapter(completion_fn=_fixed_completion)

    async def _keyword_completion(messages: list[Message]) -> str:
        return _intent_for_message(_last_user_content(messages))

    return LLMAdapter(completion_fn=_keyword_completion)
