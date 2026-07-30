"""RCA 引擎入口。

本文件提供 L/API 层需要挂接的稳定类：``DefaultRCAEngine``。

兼容 L 已定义的后端协议：
    RCAEngine.analyze(evidence: Sequence[ToolResult]) -> dict

额外提供：
- analyze_problem：独立 RCA 页面可传 problem_type / description；
- get_scenario_plan：读取四场景采证模板；
- get_evidence_steps：只取某场景的采证步骤。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mcp_servers.rca.playbooks import build_report
from mcp_servers.rca.scenarios import get_evidence_steps, get_scenario_plan


class DefaultRCAEngine:
    """默认 RCA playbook 引擎。

    这是确定性规则引擎，不是 LLM 诊断器。
    它不执行命令、不修改系统，只根据传入的不可信证据生成报告。
    """

    def analyze(
        self,
        evidence: Sequence[Any],
        *,
        problem_type: str | None = None,
        description: str = "",
        trace_id: str | None = None,
    ) -> dict:
        """分析已经采集到的证据并返回前端报告 dict。

        ``trace_id`` 是补充字段：主链路 rca.report 不需要；
        独立 RCA GET 接口若希望直接返回扁平 RcaResult，可传入 trace_id。
        """

        return dict(
            build_report(
                evidence,
                problem_type=problem_type,
                description=description,
                trace_id=trace_id,
            )
        )

    def analyze_problem(
        self,
        problem_type: str,
        description: str,
        evidence: Sequence[Any] | None = None,
        *,
        trace_id: str | None = None,
    ) -> dict:
        """独立 RCA 页面使用的便捷入口。"""

        return self.analyze(
            evidence or [],
            problem_type=problem_type,
            description=description,
            trace_id=trace_id,
        )

    def get_scenario_plan(self, problem_type: str) -> dict | None:
        """读取一个场景的采证模板，供 API/编排层使用。"""

        plan = get_scenario_plan(problem_type)
        return dict(plan) if plan is not None else None

    def get_evidence_steps(self, problem_type: str) -> list[dict]:
        """读取某个场景的采证步骤列表。"""

        return [dict(item) for item in get_evidence_steps(problem_type)]
