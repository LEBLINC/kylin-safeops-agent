"""T9：决策③ _CHANGE_TOOLS 守卫——确保所有 risk≥R2 / reversible=False 工具都在集合里。"""

from backend.app.security.path_policy import _CHANGE_TOOLS
from mcp_servers.os_ops import all_specs


def test_all_change_tools_in_guard() -> None:
    """遍历 registry 断言所有 risk≥R2 / reversible=False 工具 ∈ _CHANGE_TOOLS。"""
    specs = all_specs()
    change_tools = {s.name for s in specs if s.risk in ("R2", "R3") or not s.reversible}
    missing = change_tools - _CHANGE_TOOLS
    assert not missing, f"决策③ 漏网：{missing} 未在 _CHANGE_TOOLS"


def test_no_extra_in_guard() -> None:
    """_CHANGE_TOOLS 不含非变更类工具（防误加）。"""
    specs = all_specs()
    not_change = {s.name for s in specs if s.risk not in ("R2", "R3") and s.reversible}
    extra = _CHANGE_TOOLS & not_change
    assert not extra, f"_CHANGE_TOOLS 误加非变更类：{extra}"
