"""特权执行器（D）：命令模板白名单 + subprocess list 框架。

首版不含 systemd-run / sudoers / wrapper；等麒麟 VM 后补真沙箱版。
"""

from backend.app.executor.command_templates import (
    COMMAND_TEMPLATES,
    CommandTemplate,
    available_variants,
    get_template,
    has_tool,
)
from backend.app.executor.privilege_executor import PrivilegeExecutor

__all__ = [
    "COMMAND_TEMPLATES",
    "CommandTemplate",
    "PrivilegeExecutor",
    "available_variants",
    "get_template",
    "has_tool",
]
