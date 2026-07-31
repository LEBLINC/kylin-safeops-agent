"""之六十八 Task 1: orchestrator 驱动 RCA 场景模板采证(消费 RCA 引擎接口).

RCA 引擎 mcp_servers/rca/ 已交付 DefaultRCAEngine 含 get_scenario_plan(problem_type)
返回场景模板(RcaScenarioPlan dict,含 evidence_steps 列表,每步描述 tool/args/
purpose/required/expected_signal).本模块提供 collect_rca_evidence: 在 RCA 阶段
按场景模板跑 evidence_steps,每个 step 经 gateway.call() 收集 ToolResult.

约束:
- 仅消费 RCA 引擎接口,不修 mcp_servers/rca/ 代码(守 C3 边界)
- 仅 R0/R1 工具被采纳(非只读工具经 gateway.is_read_only 过滤跳过)
- gateway.evaluate schema 不匹配 / 工具未注册 / execute 抛错 → 跳过该 step
  (S8 fail-closed 不杀状态机,S9 is_untrusted=True 由 gateway call 路径自动密封)
- 真 VM 实证需 D/X 端到端触发,本机 CI 只走 mock gateway 路径
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING

from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.untrusted import ToolResult
from mcp_servers.rca import DefaultRCAEngine

if TYPE_CHECKING:
    from backend.app.mcp.gateway import MCPGateway

log = logging.getLogger(__name__)


def _infer_problem_type_from_intent(user_intent: str) -> str | None:
    """从 user_intent 文本推断 problem_type(简易关键词匹配,精确优先级:显式参数 > 关键词).

    与 mcp_servers/rca/models.normalize_problem_type 同口径别名表（disk/disk_usage/
    disk_full → disk_full; zombie/process_zombie → zombie_process; io/iowait → io_high;
    config/drift → config_drift; service/service_failure → service_failure）.
    """
    text = (user_intent or "").strip().lower()
    if not text:
        return None
    pattern_map = [
        (
            r"disk\s*full|disk\s+usage|disk\s+space|no\s+space\s+left|large\s+log|usage\s*%",
            "disk_full",
        ),
        (r"zombie|defunct|process_zombie", "zombie_process"),
        (r"iowait|i/o\s*high|io\s+high|disk\s*i/o", "io_high"),
        (r"config\s*drift|hash\s*mismatch|baseline\s*mismatch", "config_drift"),
        (r"service\s*fail|service\s*down|unit\s*inactive|unit\s*failed", "service_failure"),
        # 中文触发词：产品面向中文运维场景，纯英文正则会让五套采证模板对
        # 中文输入全部不可达（模板已实现，只是入不了口）。
        # 与英文分支同表同优先级，不新增语义、不改模板。
        (
            r"磁盘.{0,4}(满|不足|爆)|空间.{0,4}(满|不足|紧张)|清理.{0,4}(垃圾|空间|磁盘)"
            r"|垃圾.{0,2}文件|大文件|日志.{0,2}(占满|过大)",
            "disk_full",
        ),
        (r"僵尸进程|僵死进程", "zombie_process"),
        (r"io.{0,4}(高|飙|满)|读写.{0,4}(高|慢)|磁盘.{0,2}io", "io_high"),
        (r"配置.{0,2}(漂移|变更|被改)|基线.{0,2}(不符|不一致)", "config_drift"),
        (r"服务.{0,4}(挂|失败|起不来|异常|停了)|进程.{0,2}退出", "service_failure"),
    ]
    for pattern, problem_type in pattern_map:
        if re.search(pattern, text):
            return problem_type
    return None


def resolve_problem_type(
    rca_engine: DefaultRCAEngine,
    user_intent: str,
    explicit_problem_type: str | None,
) -> str | None:
    """二段优先级: 显式参数 > user_intent 关键词推断; 两者均 None → 返回 None（后续 collect 跳过）.

    显式参数与 user_intent 任一非 None 即返回;两者都为空 → None.
    （注：引擎 analyze 推断为预留设计位，当前不实现，不调用 rca_engine.analyze）
    """
    if explicit_problem_type:
        return explicit_problem_type
    return _infer_problem_type_from_intent(user_intent)


async def collect_rca_evidence(
    gateway: MCPGateway,
    rca_engine: DefaultRCAEngine,
    user_intent: str,
    *,
    problem_type: str | None = None,
    budget_s: float | None = None,
) -> list[ToolResult]:
    """按 RCA 场景模板驱动 evidence 采集.

    1. resolve_problem_type 决定场景;
    2. rca_engine.get_scenario_plan(type) 取 evidence_steps;
    3. 每个 step 构造 CandidateTool,经 gateway.is_read_only / gateway.call 跑;
    4. 失败/非只读/未注册/schema 不匹配 → 跳过该 step,不抛错不中断.

    返回 collected ToolResult 列表(可能为空,此时调用方应 fallback 到已有 evidence 不变).

    budget_s: 整轮采证的时间上界(秒)。None = 无上界(默认，chat 主链路行为不变)。
        非 None 时：每步 wait_for 剩余预算，预算耗尽即停止启动新步骤，
        **按已采到的部分返回**——不抛 TimeoutError、不返回空列表。
        存在理由：HTTP 同步请求里跑 N 个只读工具，真机上 find 无 -xdev/-size
        约束时单步可达 30s(P2-7)，没有上界会把一次 RCA 查询挂死。
        用界限而不是用"默认关的开关"来约束，能力仍然默认可用。
    """
    deadline = None if budget_s is None else time.monotonic() + budget_s
    resolved = resolve_problem_type(rca_engine, user_intent, problem_type)
    if not resolved:
        log.debug("collect_rca_evidence: no problem_type resolvable, skip")
        return []

    plan = rca_engine.get_scenario_plan(resolved)
    if not plan:
        log.debug("collect_rca_evidence: no scenario plan for %s, skip", resolved)
        return []

    steps: Sequence[dict] = plan.get("evidence_steps") or []
    if not steps:
        log.debug("collect_rca_evidence: empty evidence_steps for %s, skip", resolved)
        return []

    collected: list[ToolResult] = []
    for step in steps:
        if deadline is not None and time.monotonic() >= deadline:
            log.warning(
                "collect_rca_evidence: 采证预算耗尽，按已采到的 %d 条出报告（剩余步骤跳过）",
                len(collected),
            )
            break
        tool_name = str(step.get("tool", ""))
        step_args = dict(step.get("args") or {})
        if not tool_name:
            continue

        candidate = CandidateTool(name=tool_name, args=step_args)

        # schema 预校验: 不通过 → 跳过(不抛错,模板与 registry 不一致由本路径 fail)
        verdict = gateway.evaluate(candidate)
        if verdict.decision == "deny":
            log.debug(
                "collect_rca_evidence: step %s deny verdict (%s), skip",
                tool_name,
                verdict.reason,
            )
            continue

        # 只读闸: 非 R0/R1 → 跳过(防 RCA 阶段触发变更工具)
        if not gateway.is_read_only(candidate):
            log.warning(
                "collect_rca_evidence: step %s not read-only (risk=%s), skip — RCA 不跑变更工具",
                tool_name,
                verdict.final_risk,
            )
            continue

        try:
            if deadline is None:
                outcome = await gateway.call(candidate, approved=False)
            else:
                outcome = await asyncio.wait_for(
                    gateway.call(candidate, approved=False),
                    timeout=max(0.0, deadline - time.monotonic()),
                )
        except asyncio.TimeoutError:
            # 用 asyncio.TimeoutError 而非内建 TimeoutError：3.10 上两者不是同一个类
            # （3.11 起才别名统一），本仓 3.10/3.11 双跑。
            log.warning(
                "collect_rca_evidence: step %s 超出采证预算 — skip（已采 %d 条）",
                tool_name,
                len(collected),
            )
            continue
        except Exception as exc:
            log.warning(
                "collect_rca_evidence: gateway.call(%s) failed: %s — skip (S8 兜底)",
                tool_name,
                exc,
            )
            continue
        if not outcome.executed or outcome.result is None:
            continue
        collected.append(outcome.result)

    return collected
