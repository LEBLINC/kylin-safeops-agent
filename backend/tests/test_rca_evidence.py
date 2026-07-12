"""R3 /api/rca/analyze evidence 接入测试（X 联调新增）。

覆盖 2 用例（+1 兜底）：
  - T1：传 evidence → 响应 evidence_count > 0，RCA 引擎拿到证据
  - T2：不传 evidence → evidence_count=0（兜底走 problem_type/description 模板壳子）
  - T2b：显式 evidence=[] → evidence_count=0

全部走 DefaultRCAEngine 真分析（确定性规则引擎，不触网、不执行命令）。
conftest 已 autouse 设 KYLIN_AUTH_MODE=dev，verify_token 自动放行。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routers import rca as rca_module


@pytest.fixture(autouse=True)
def _reset_reports() -> None:
    """每个 case 清空 RCA 内存报告暂存（避免 trace_id 跨 case 命中）。"""
    rca_module._reports.clear()
    yield
    rca_module._reports.clear()


@pytest.fixture
def client() -> TestClient:
    """装配 TestClient：审计库 :memory:（conftest 已钉），dev 联调态 verify_token 自动放行。"""
    from backend.app.api.app import create_app

    return TestClient(create_app())


# ---- T1: 传 evidence → evidence_count > 0 ----------------------------------


def test_rca_analyze_with_evidence_count_nonzero(client: TestClient) -> None:
    """RCA 端点接收 evidence → 透传给引擎 → 响应 evidence_count > 0。

    X 联调新增：前端把已观测/已执行的 tool_result dict 喂进 RCA，真走 playbook。
    """
    evidence = [
        {
            "tool_name": "disk.usage",
            "stdout": "/dev/sda1  50G  48G  2G  96% /",
            "exit_code": 0,
            "tool_result": {"use_percent": 96.0, "mount_point": "/"},
        },
        {
            "tool_name": "process.list",
            "stdout": "PID TTY STAT TIME COMMAND\n1 ? Ss 0:01 init",
            "exit_code": 0,
            "tool_result": {"processes": [{"stat": "Ss"}]},
        },
    ]
    resp = client.post(
        "/api/rca/analyze",
        json={
            "problem_type": "disk_full",
            "description": "/dev/sda1 96% full, please find why",
            "evidence": evidence,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "trace_id" in body
    assert body["evidence_count"] == 2

    # 真接：报告非空且 evidence_chain 链条含我们喂的 2 条
    report_resp = client.get(f"/api/rca/{body['trace_id']}")
    assert report_resp.status_code == 200
    report = report_resp.json()["report"]
    assert isinstance(report, dict)
    # DefaultRCAEngine.build_report 把 evidence 转 evidence_chain（list[dict]）
    chain = report.get("evidence_chain", [])
    assert len(chain) >= 2, f"expected >=2 evidence_chain items, got {len(chain)}"


# ---- T2: 不传 evidence → evidence_count=0 兜底 ------------------------------


def test_rca_analyze_without_evidence_count_zero(client: TestClient) -> None:
    """RCA 端点不传 evidence → evidence_count=0 兜底（problem_type/description 模板壳子）。

    X 联调新增：前端 RCA 页可先开壳子（采集建议模板），用户后续补 evidence。
    """
    resp = client.post(
        "/api/rca/analyze",
        json={"problem_type": "disk_full", "description": "stub request without evidence"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "trace_id" in body
    assert body["evidence_count"] == 0

    # 兜底：仍产"采集建议"型非空报告（DefaultRCAEngine.analyze_problem 行为）
    report_resp = client.get(f"/api/rca/{body['trace_id']}")
    assert report_resp.status_code == 200
    report = report_resp.json()["report"]
    assert isinstance(report, dict)
    # 采集建议模板应含 next_steps / recommended_tools 等键
    assert report, "fallback report should be non-empty"


def test_rca_analyze_empty_evidence_array_count_zero(client: TestClient) -> None:
    """RCA 端点显式传 evidence=[] → 等价不传 → evidence_count=0。"""
    resp = client.post(
        "/api/rca/analyze",
        json={"problem_type": "disk_full", "description": "explicit empty", "evidence": []},
    )
    assert resp.status_code == 200
    assert resp.json()["evidence_count"] == 0
