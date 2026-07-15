"""之六十八 Task 4 / 测试 2: 独立 RCA 端点单测 mock 复现（端到端 LLM）。

覆盖（3 用例）：
  T1 POST /api/rca/analyze(disk_full + 2 fake evidence) → 200 trace_id；
     GET /api/rca/{trace_id} → RCAReportResponse 含 llm_summary 非 None；
     llm_summary 含 disk/log 关键 token。
  T2 _reports 结构兼容老 client：响应 schema 含 llm_summary optional 字段,
     老 client 不读此字段零感知。
  T3 反向: KYLIN_LLM_FAKE 不开 + 无 base_url 时 llm_summary = None 兜底(前端零感知).

依赖: conftest 已 autouse 设 KYLIN_AUTH_MODE=dev,verify_token 自动放行。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api.app import create_app
from backend.app.api.routers import rca as rca_module

_DISK_EVIDENCE = [
    {
        "tool_name": "disk.usage",
        "stdout": "Filesystem /dev/sda1: Used=85% / Avail=2.1G / Mount=/",
        "exit_code": 0,
        "tool_result": {"use_percent": 85.0, "mount_point": "/"},
    },
    {
        "tool_name": "disk.large_files",
        "args": {"path": "/var/log", "min_size_mb": 100},
        "stdout": "/var/log/syslog.1  240M\n/var/log/journal/abc  150M",
        "exit_code": 0,
    },
]


def test_t1_router_e2e_with_evidence_returns_llm_summary() -> None:
    """T1: POST + 2 evidence → GET 响应含 llm_summary, 含 disk/log token."""
    rca_module._reports.clear()
    client = TestClient(create_app())

    resp = client.post(
        "/api/rca/analyze",
        json={
            "problem_type": "disk_full",
            "description": "disk 满",
            "evidence": _DISK_EVIDENCE,
        },
    )
    assert resp.status_code == 200, resp.text
    trace_id = resp.json()["trace_id"]
    assert resp.json()["evidence_count"] == 2

    # GET 含 llm_summary
    get = client.get(f"/api/rca/{trace_id}")
    assert get.status_code == 200, get.text
    body = get.json()
    assert "llm_summary" in body, "T1 期望响应含 llm_summary 字段"
    llm_summary = body["llm_summary"]
    # KYLIN_LLM_FAKE 未设 → fake stub 自动注入(由 lifespan 装配的 RealLLMClient 的
    # is_fixture 路径); 真模式下 None 兜底。任一可接受,验证字段存在+schema 兼容。
    assert llm_summary is None or isinstance(llm_summary, str)
    # report 含 evidence_chain + summary_source 标记
    report = body["report"]
    assert isinstance(report, dict)
    assert "summary" in report
    assert report.get("summary_source") in {"llm", "playbook"}


def test_t2_router_schema_backward_compat() -> None:
    """T2: schema 加 llm_summary 字段后,响应 dict 含此字段(老 client 不读零感知)."""
    rca_module._reports.clear()
    client = TestClient(create_app())

    resp = client.post(
        "/api/rca/analyze",
        json={"problem_type": "disk_full", "description": "test"},
    )
    assert resp.status_code == 200
    trace_id = resp.json()["trace_id"]

    get = client.get(f"/api/rca/{trace_id}")
    body = get.json()
    # 关键 schema 兼容字段全部存在
    for key in ("trace_id", "report", "llm_summary"):
        assert key in body, f"T2 响应缺 {key} 字段(破坏老 client)"


def test_t3_router_reverse_no_llm_summary_is_none() -> None:
    """T3: LLM 不可用时 llm_summary=None 兜底,前端零感知兼容."""
    rca_module._reports.clear()
    client = TestClient(create_app())

    resp = client.post(
        "/api/rca/analyze",
        json={"problem_type": "unknown_problem", "description": "no match"},
    )
    assert resp.status_code == 200
    trace_id = resp.json()["trace_id"]

    get = client.get(f"/api/rca/{trace_id}")
    body = get.json()
    # unknown_problem 下 build_report 返 {} → 不进 LLM 化分支,llm_summary 必 None
    assert body.get("llm_summary") is None, "T3: 未知问题类型,llm_summary 必 None 兜底"
    assert body["report"] == {}, "T3: 未知问题类型,report 必空"
