"""Kylin SafeOps Agent - RCA playbook 包。

本包归 X（xizi-9527）负责，放在 ``mcp_servers/rca/``，不触碰
``backend/app/contracts/`` 和 L/D 的后端内核。

本版严格对齐文档中的五个 RCA 场景：
- disk_full：磁盘满 / 大日志；
- zombie_process：僵尸进程；
- io_high：磁盘 I/O 异常；
- config_drift：配置漂移；
- service_failure：服务异常。

``unknown`` 只是证据不足时的兜底返回，不作为第六个演示场景。
"""

from __future__ import annotations

from mcp_servers.rca.engine import DefaultRCAEngine
from mcp_servers.rca.models import normalize_problem_type
from mcp_servers.rca.playbooks import build_report
from mcp_servers.rca.scenarios import (
    RCA_SCENARIOS,
    get_evidence_steps,
    get_scenario_plan,
    list_scenario_plans,
)

__all__ = [
    "DefaultRCAEngine",
    "RCA_SCENARIOS",
    "normalize_problem_type",
    "build_report",
    "get_evidence_steps",
    "get_scenario_plan",
    "list_scenario_plans",
]
