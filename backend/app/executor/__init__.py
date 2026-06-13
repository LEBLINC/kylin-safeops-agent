"""特权执行器（D）：命令模板白名单 + subprocess list 框架 + systemd-run 沙箱（PR2b）。

沙箱默认关闭（sandbox_enabled=False）；麒麟 VM 上由 L 在 app.py lifespan 显式启用。
"""

from backend.app.executor.command_templates import (
    COMMAND_TEMPLATES,
    CommandTemplate,
    available_variants,
    get_template,
    has_tool,
)
from backend.app.executor.privilege_executor import PrivilegeExecutor
from backend.app.executor.sandbox import (
    TOOL_SANDBOX_PROFILES,
    SandboxConfig,
    SandboxProfile,
    build_sandbox_argv,
    get_sandbox_profile,
    is_sandbox_available,
)

__all__ = [
    "COMMAND_TEMPLATES",
    "TOOL_SANDBOX_PROFILES",
    "CommandTemplate",
    "PrivilegeExecutor",
    "SandboxConfig",
    "SandboxProfile",
    "available_variants",
    "build_sandbox_argv",
    "get_sandbox_profile",
    "get_template",
    "has_tool",
    "is_sandbox_available",
]
