"""C1（阶段6 第二梯队）：自研轻量 counter/gauge 指标系统。

**勿引 prometheus_client**——LoongArch 离线部署 wheel 风险与 T6 治债同类；
自研 dict-based 实现零第三方依赖，满足当前埋点粒度（状态计数/调用计数/瞬时延迟/连接数）。

放在 agent/ 而非 api/：orchestrator（本包）是主要埋点源（状态机各阶段计数 + 审计
append 延迟）；llm/adapter.py 与 api/routers/system.py 均从本叶子模块读取，
本模块自身零依赖，不产生循环导入。

进程内单实例，asyncio 单线程事件循环下字典读写天然原子，无需锁；
不支持多进程聚合（麒麟靶机单节点部署，与 EventBus/SessionRegistry 同前提）。
"""

from __future__ import annotations


class Metrics:
    """进程内单实例 counter/gauge 存储。"""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}

    def inc(self, name: str, amount: int = 1) -> None:
        """counter 累加（只增，如调用次数/失败数/状态计数）。"""
        self._counters[name] = self._counters.get(name, 0) + amount

    def set_gauge(self, name: str, value: float) -> None:
        """gauge 覆写（反映瞬时值，如最近一次审计 append 延迟）。"""
        self._gauges[name] = value

    def snapshot(self) -> dict[str, dict[str, int] | dict[str, float]]:
        """返回当前全部 counters/gauges 的浅拷贝，供 /api/system/metrics 序列化。"""
        return {"counters": dict(self._counters), "gauges": dict(self._gauges)}

    def reset(self) -> None:
        """测试专用：清空所有指标，防跨用例污染。"""
        self._counters.clear()
        self._gauges.clear()


_metrics = Metrics()


def get_metrics() -> Metrics:
    """获取全局 Metrics 单例。"""
    return _metrics
