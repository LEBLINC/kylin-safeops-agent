"""P1-1: 协作者代号不得进入产品运行时输出（实跑断言，非源码正则）。

为什么必须"实跑"而不是扫源码：这类命中恰好都在**字段值**里，源码正则按
"注释/docstring"的模式去找会整类漏掉：
  - playbooks.py 的 "Suggest L/D add disk.iostat..." 是 recommendations 的
    正式字段值 → 进 RCA 报告 → 进 API 响应 → 直接渲染到前端 UI
  - schemas.py 的 "RCA 报告（结构待 X 定）" 是 Field(description=...) →
    必进 /openapi.json → 点开 /docs 就是第一现场

故本用例把产品出口**真渲染出来**再扫：
  R-1 create_app().openapi() 序列化后扫代号 = 0
  R-2 全量 ToolSpec 序列化 + 五套 playbook 报告/采证模板的字段值扫代号 = 0
  R-3 契约层包 docstring 不含代号（契约随交付包分发）
"""

from __future__ import annotations

import json
import re

#: 代号形态枚举（教训：应枚举**出现形态**而非语义句式）。
_CODENAME_RE = re.compile(
    r"(?<![A-Za-z])[DLX](?:\s*[/、+]\s*[DLX])*\s*(?:域|侧|的|拿|定|加|做|接|派|单)"
    r"|(?<![A-Za-z])[DLX]\s+(?:add|拍板|实现|负责|落地)"
    r"|Suggest\s+[DLX](?:\s*/\s*[DLX])*\s"
    r"|待\s*[DLX]\s*定"
)

#: 大写状态词的尾字母会误命中（如 "FINISHED 的"），先剔除再扫。
_ALLOW = re.compile(r"(FINISHED|REJECTED|EXECUTED|EXECUTING|VERIFIED|FAILED|APPROVED|SETEX)")


def _hits(text: str) -> list[str]:
    return [m.group(0) for m in _CODENAME_RE.finditer(_ALLOW.sub("", text))]


def test_r1_openapi_has_no_codename(monkeypatch) -> None:
    """R-1: /openapi.json 序列化后不得含代号——点开 /docs 即第一现场。"""
    monkeypatch.setenv("KYLIN_AUTH_MODE", "dev")
    monkeypatch.setenv("KYLIN_LLM_FAKE", "true")

    from backend.app.api.app import create_app

    spec = json.dumps(create_app().openapi(), ensure_ascii=False)
    hits = _hits(spec)
    assert not hits, f"R-1: /openapi.json 含代号 {sorted(set(hits))}"


def test_r2_tool_specs_and_playbook_reports_clean() -> None:
    """R-2: 工具清单与五套 RCA 报告的**字段值**不得含代号。

    这些内容经 /api/tools/registry 与 rca 事件直达前端 UI。
    """
    from mcp_servers.os_ops import all_specs
    from mcp_servers.rca import DefaultRCAEngine

    specs = list(all_specs())
    assert specs, "R-2: 工具清单为空（用例前提失效）"
    registry_dump = json.dumps([s.model_dump() for s in specs], ensure_ascii=False)
    assert not _hits(registry_dump), f"R-2: ToolSpec 含代号 {sorted(set(_hits(registry_dump)))}"

    engine = DefaultRCAEngine()
    for scenario in ("disk_full", "zombie_process", "io_high", "config_drift", "service_failure"):
        report = engine.analyze_problem(scenario, f"{scenario} 演练", [])
        hits = _hits(json.dumps(report, ensure_ascii=False))
        assert not hits, f"R-2: {scenario} 报告字段值含代号 {sorted(set(hits))}"

        plan_hits = _hits(json.dumps(engine.get_scenario_plan(scenario), ensure_ascii=False))
        assert not plan_hits, f"R-2: {scenario} 采证模板含代号 {sorted(set(plan_hits))}"


def test_r3_contracts_package_docstring_clean() -> None:
    """R-3: 契约层包 docstring 不含代号（契约是最显眼的架构文件）。"""
    import backend.app.contracts as contracts_pkg

    hits = _hits(contracts_pkg.__doc__ or "")
    assert not hits, f"R-3: contracts/__init__.py docstring 含代号 {sorted(set(hits))}"
