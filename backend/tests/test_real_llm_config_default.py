"""B5 commit 4 + 之七十五 M-5: LLM 配置 fail-closed 默认 + readiness 阈值语义。

覆盖:
  T1  未配 env 时 fail-closed 到 fixture 态（不静默联真网）
  T1b 显式配 real 时确实切到 real（防 T1 被"永远 fixture"糊弄）
  M5-1 readiness 阈值随 KYLIN_SSE_MAX_CONN 变化（真调端点，非只读 env）
  M5-2 readiness 阈值**不受** KYLIN_SSE_QUEUE_MAX 影响（语义解耦守门）
  M5-3 未达阈值 → 200 ready=True
  M5-4 审计库 ping 失败 → 503（db 位真参与判定）

M-5 背景：原 T2 断言的是"自己刚 setenv 的值等于该值"，既没调 readiness、也没验
任何行为——是一条恒真断言（假绿）。而它守的那行代码恰好有语义错配：
readiness 读的是 KYLIN_SSE_QUEUE_MAX（单队列事件深度，H-2 起默认 512），
却用来卡 bus.active_count（活跃连接数）。运维一旦按 H-2 显式 export
KYLIN_SSE_QUEUE_MAX=512，阈值会静默从 100 放大到 512 连接。
M-5 改读 KYLIN_SSE_MAX_CONN，本文件同步换成真行为断言。
"""

from __future__ import annotations

import asyncio

from backend.app.api.event_bus import EventBus


def test_t1_env_defaults_fail_closed_to_fixture() -> None:
    """T1: 未配 env 时装配出的配置必须 fail-closed 到不联网的 fixture 态。

    原断言是 `assert cfg is not None`——构造成功即恒真，无为假分支；
    函数名还叫 ..._warns，但 RealLLMConfig 是纯 dataclass，从不 warn，
    docstring 说的"默认 base_url 是示例 placeholder"也与实际不符
    （默认值是真实 dashscope 地址）。名实、断言三处皆不对。

    这里改断真正该守的不变量：**没给 env 就绝不能默认联真网**。
    provider 默认 fixture、api_key 默认空——任一被改成"真端点"型默认值，
    都会让未配置的部署静默出网，本用例即为该回归的守门。
    """
    import os

    from backend.app.llm.real_client import load_real_llm_config_from_env

    saved = {
        k: os.environ.pop(k, None)
        for k in ("KYLIN_LLM_PROVIDER", "KYLIN_LLM_API_KEY", "KYLIN_LLM_BASE_URL")
    }
    try:
        cfg = load_real_llm_config_from_env()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v

    assert cfg.provider == "fixture", (
        f"T1: 未配 KYLIN_LLM_PROVIDER 时应 fail-closed 到 fixture，实际 {cfg.provider!r}"
        "——未配置的部署会静默联真网"
    )
    assert cfg.api_key == "", "T1: 默认不得内置 api_key"
    assert (
        "localhost" in cfg.base_url
    ), f"T1: 默认 base_url 应指向本地而非外网，实际 {cfg.base_url!r}"


def test_t1b_explicit_real_provider_is_honored() -> None:
    """T1b: 显式配 real 时必须真的切到 real——防上一条被"永远返回 fixture"糊弄过去。"""
    import os

    from backend.app.llm.real_client import load_real_llm_config_from_env

    saved = os.environ.get("KYLIN_LLM_PROVIDER")
    os.environ["KYLIN_LLM_PROVIDER"] = "real"
    try:
        cfg = load_real_llm_config_from_env()
    finally:
        if saved is None:
            os.environ.pop("KYLIN_LLM_PROVIDER", None)
        else:
            os.environ["KYLIN_LLM_PROVIDER"] = saved

    assert cfg.provider == "real", "T1b: 显式配置未生效"


class _StubAudit:
    """readiness 只用到 ping()。"""

    def __init__(self, *, ping_ok: bool = True) -> None:
        self._ping_ok = ping_ok

    def ping(self) -> bool:
        if not self._ping_ok:
            raise RuntimeError("db down")
        return True


def _call_readiness(bus: EventBus, *, ping_ok: bool = True):
    from backend.app.api.routers.system import readiness

    return asyncio.run(readiness(audit=_StubAudit(ping_ok=ping_ok), bus=bus, registry=None))


def _fill(bus: EventBus, n: int) -> None:
    for i in range(n):
        bus.create(f"conn-{i}")


def test_m5_1_threshold_follows_max_conn(monkeypatch) -> None:
    """M5-1: 活跃连接达 KYLIN_SSE_MAX_CONN → 503（阈值真生效，非只读 env）。"""
    monkeypatch.setenv("KYLIN_SSE_MAX_CONN", "3")
    monkeypatch.delenv("KYLIN_SSE_QUEUE_MAX", raising=False)
    bus = EventBus()
    _fill(bus, 3)  # active_count == 3，不满足 active < 3

    resp = _call_readiness(bus)
    assert getattr(resp, "status_code", 200) == 503, "M5-1: 达上限应 503"


def test_m5_2_threshold_ignores_queue_max(monkeypatch) -> None:
    """M5-2: KYLIN_SSE_QUEUE_MAX 不得影响 readiness 阈值（语义解耦）。

    这是 M-5 的核心断言：把 QUEUE_MAX 设成远大于连接数的值，若 readiness 仍读它，
    则本该 503 的场景会变成 200（探针失效）。
    """
    monkeypatch.setenv("KYLIN_SSE_MAX_CONN", "3")
    monkeypatch.setenv("KYLIN_SSE_QUEUE_MAX", "512")  # 干扰项：语义无关，不得生效
    bus = EventBus()
    _fill(bus, 3)

    resp = _call_readiness(bus)
    assert (
        getattr(resp, "status_code", 200) == 503
    ), "M5-2: readiness 阈值被 KYLIN_SSE_QUEUE_MAX 放大——语义错配未修"


def test_m5_3_below_threshold_ready(monkeypatch) -> None:
    """M5-3: 未达阈值 + db ok → 200 且 ready=True。"""
    monkeypatch.setenv("KYLIN_SSE_MAX_CONN", "10")
    bus = EventBus()
    _fill(bus, 2)

    resp = _call_readiness(bus)
    assert getattr(resp, "status_code", 200) == 200
    assert resp.ready is True
    assert resp.active_sessions == 2


def test_m5_4_db_failure_makes_not_ready(monkeypatch) -> None:
    """M5-4: 审计库 ping 抛异常 → 503（db 位真参与判定，不是装饰）。"""
    monkeypatch.setenv("KYLIN_SSE_MAX_CONN", "10")
    bus = EventBus()

    resp = _call_readiness(bus, ping_ok=False)
    assert getattr(resp, "status_code", 200) == 503
