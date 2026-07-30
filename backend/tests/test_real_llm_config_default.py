"""B5 commit 4 + 之七十五 M-5: RealLLMConfig 默认 warning + readiness 阈值语义。

覆盖:
  T1 RealLLMConfig() 实例化 → 不 crash（默认 base_url 是示例 placeholder）
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


def test_t1_real_llm_config_default_warns(caplog) -> None:
    """T1: RealLLMConfig() 默认 base_url 是示例 placeholder，实例化不得 crash。"""
    from backend.app.llm.real_client import RealLLMConfig

    with caplog.at_level("WARNING"):
        cfg = RealLLMConfig(api_key="")
    assert cfg is not None


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
