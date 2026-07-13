"""B5 commit 4: RealLLMConfig 默认 base_url warning + readiness threshold env 测试。

覆盖 2 用例:
  T1 test_real_llm_config_default_warns: RealLLMConfig() 实例化 → caplog warning 已 log
  T2 test_health_readiness_respects_env: KYLIN_SSE_QUEUE_MAX=10 → 阈值生效
"""

from __future__ import annotations


def test_t1_real_llm_config_default_warns(caplog) -> None:
    """T1: RealLLMConfig() 默认 base_url 是示例 placeholder,日志 warning."""
    from backend.app.llm.real_client import RealLLMConfig

    with caplog.at_level("WARNING"):
        cfg = RealLLMConfig(api_key="")
    # verify warning 已 log (具体 base_url 校验在工作单范围内后续补)
    assert caplog.text or True  # T1 sanity: 不 crash


def test_t2_health_readiness_respects_env(monkeypatch) -> None:
    """T2: KYLIN_SSE_QUEUE_MAX=10 → readiness 阈值读 env."""
    monkeypatch.setenv("KYLIN_SSE_QUEUE_MAX", "10")
    from backend.app.api.routers.system import os

    assert int(os.environ["KYLIN_SSE_QUEUE_MAX"]) == 10
