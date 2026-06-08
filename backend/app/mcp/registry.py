"""MCP 工具注册表（手册 §3.3）。

加载所有 ToolSpec（契约1），提供 list_tools() / get(name)。
纯内存注册，无 IO；os_ops 的工具在启动时注册进来（D6+ 增量）。
"""

from __future__ import annotations

from collections.abc import Iterable

from backend.app.contracts.tool import ToolSpec


class ToolRegistry:
    """工具规格注册表：名称唯一，按名查询。"""

    def __init__(self, specs: Iterable[ToolSpec] | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        """注册一个工具规格；重名拒绝（防覆盖/影子工具）。"""
        if spec.name in self._specs:
            raise ValueError(f"duplicate tool name: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        """按名取规格；不存在返回 None。"""
        return self._specs.get(name)

    def has(self, name: str) -> bool:
        return name in self._specs

    def list_tools(self) -> list[ToolSpec]:
        """返回所有已注册规格（按名称排序，输出稳定）。"""
        return [self._specs[k] for k in sorted(self._specs)]
