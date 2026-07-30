"""之七十五 M-9: service.status 场景模板 schema 与 registry 口径一致。

修前：RCA 场景模板写 args={"unit": ""}，而 service.status 的 input_schema 是
required=["service_name"] + additionalProperties=False——该步必被 gateway 的
schema 闸拒。后果是**静默失效**：collect_rca_evidence 对 deny 只 log.debug + skip
（这是设计好的 fail-soft，不抛错不中断状态机），于是 service_failure 场景里
"查服务状态"这一步从未真正采到证据，而任何日志/报告都看不出缺了它。

  M9-1 模板字段名与 registry input_schema 一致（不含 unit，含 service_name）
  M9-2 该步真正通过 gateway schema 闸（evaluate 非 deny）——即真进采证，不被 skip
  M9-3 采证链路上用真 evaluate 走一遍（executor 仍为假；非全链路端到端）
  M9-4 与 H-1 wrapper 自洽：模板取值经命令模板拼出的 argv 仍是
       systemctl show <service_name>，落在 wrapper 动词白名单内
"""

from __future__ import annotations

import asyncio

from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.untrusted import ToolResult
from backend.app.mcp.gateway import CallOutcome
from mcp_servers.rca import DefaultRCAEngine

_SCENARIO = "service_failure"


def _status_step() -> dict:
    plan = DefaultRCAEngine().get_scenario_plan(_SCENARIO)
    steps = [s for s in plan["evidence_steps"] if s["tool"] == "service.status"]
    assert steps, "M9: service_failure 场景应含 service.status 步骤"
    return steps[0]


def test_m9_1_template_field_matches_registry() -> None:
    """M9-1: 模板 args 用 service_name，不再用 registry 不认的 unit。"""
    args = _status_step()["args"]
    assert "service_name" in args, "M9-1: 应用 registry 口径字段名 service_name"
    assert "unit" not in args, "M9-1: unit 不在 service.status 的 input_schema 内"
    assert args["service_name"], "M9-1: 取值不能为空串（schema minLength=1）"


def test_m9_2_step_passes_gateway_schema_gate() -> None:
    """M9-2: 该步经真 registry + 真策略引擎 evaluate 不被 deny（真进采证）。"""
    from backend.app.api._fakes import build_gateway

    gateway = build_gateway()
    step = _status_step()
    verdict = gateway.evaluate(CandidateTool(name="service.status", args=step["args"]))
    assert (
        verdict.decision != "deny"
    ), f"M9-2: 该步仍被闸拒（{verdict.reason}）——模板与 registry 未对齐，采证静默失效"


def test_m9_3_collect_passes_real_schema_gate() -> None:
    """M9-3: 用**真** gateway 的 evaluate 走采证——该步不被 schema 闸 skip。

    覆盖面说明（刻意不写"端到端"）：executor 仍是假的，只有闸是真的。
    这正是本用例要守的东西——M-9 修的缺陷就发生在 schema 闸上，
    原实现把 gateway.evaluate mock 成恒 allow，等于把被测对象本身 mock 掉了：
    把模板 args 还原成 {"unit": ""} 该用例照样全绿（已实测）。
    真执行不在此验（需要真 systemd），由 M9-4 的 argv 自洽断言另行覆盖。
    """
    from backend.app.agent.rca_drive import collect_rca_evidence
    from backend.app.api._fakes import build_gateway

    engine = DefaultRCAEngine()
    called: list[str] = []

    real_gateway = build_gateway()

    class _GatewayWithFakeExec:
        """真 evaluate / 真 is_read_only，仅把执行换成假的。"""

        def evaluate(self, tool: CandidateTool):  # noqa: ANN202
            return real_gateway.evaluate(tool)

        def is_read_only(self, tool: CandidateTool) -> bool:
            return real_gateway.is_read_only(tool)

        async def call(self, tool: CandidateTool, **_kw) -> CallOutcome:
            # 先过真闸：被 deny 就如实返回未执行，不伪造成功
            verdict = real_gateway.evaluate(tool)
            if verdict.decision == "deny":
                return CallOutcome(executed=False, verdict=verdict, reason=verdict.reason)
            called.append(tool.name)
            return CallOutcome(
                executed=True,
                result=ToolResult(
                    tool=tool.name,
                    args=tool.args,
                    exit_code=0,
                    stdout_truncated="ActiveState=failed",
                ),
            )

    collected = asyncio.run(
        collect_rca_evidence(
            _GatewayWithFakeExec(), engine, "service failed", problem_type=_SCENARIO
        )
    )

    assert (
        "service.status" in called
    ), "M9-3: service.status 未被调用——模板 args 被真 schema 闸拒后静默 skip"
    assert any(r.tool == "service.status" for r in collected), "M9-3: 采证结果应含该工具"


def test_m9_4_consistent_with_h1_wrapper_verb_whitelist() -> None:
    """M9-4: 与 H-1 wrapper 自洽——argv 仍是 systemctl show <name>，在动词白名单内。

    M-9 只改字段名不该影响 argv，但 H-1 刚给 wrapper 加了 systemctl 动词白名单
    （仅 show/restart），故显式验一遍二者仍自洽：字段名改动不得让 argv 拼出
    白名单外的动词，也不得让服务名位置落进"选项"形态（- 开头会被 wrapper 拒）。
    """
    from backend.app.executor.command_templates import COMMAND_TEMPLATES

    tpl = COMMAND_TEMPLATES["service.status"]["default"]
    assert tpl.argv_prefix == ["/usr/bin/systemctl", "show"], "M9-4: argv 前缀不应变"
    assert tpl.dynamic_args == ["service_name"], "M9-4: 动态参数名应与模板字段一致"

    service_name = _status_step()["args"]["service_name"]
    assert not service_name.startswith(
        "-"
    ), "M9-4: 服务名不得以 - 开头——H-1 wrapper 会把动词后的 - 开头参数判为选项注入并拒"
