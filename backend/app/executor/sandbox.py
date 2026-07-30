"""systemd 瞬态 service 沙箱 — wrapper 唯一执行入口。

机制：systemd-run 瞬态 service（非 scope）。scope 只做 cgroup 登记、不经 fork/exec，
所有依赖 mount namespace 的保护属性（ProtectSystem/ReadOnlyPaths/PrivateTmp/...）
在 scope 下被静默忽略；瞬态 service 由 systemd 真 fork/exec，Protect* 才真正落地。

Python 只选 profile 并构建经 wrapper 的 argv；安全属性硬编码在 wrapper 中
（deploy/sandbox/kylin-safeops-run.sh，单一事实来源）。即使 Agent 进程被攻陷，
也无法通过 -p 注入削弱沙箱（sudoers 仅放行 wrapper 路径，闭合 O12）。

sandbox_enabled=False 默认关，开启由 app.py lifespan 传入。
"""

from __future__ import annotations

import os
import platform
import shutil
from collections.abc import Sequence
from typing import Literal

SandboxProfile = Literal["readonly", "limited_write", "none"]

#: 沙箱唯一执行入口（wrapper 脚本部署路径）。
WRAPPER_PATH = "/usr/local/sbin/kylin-safeops-run.sh"
#: sudo 绝对路径。
SUDO_PATH = "/usr/bin/sudo"

#: 工具 → profile 映射（显式注册；未注册默认 readonly，保守 fail-closed）。
TOOL_SANDBOX_PROFILES: dict[str, SandboxProfile] = {
    # system.info 不经沙箱：profile=none 使 build_sandbox_argv 直接返回原 argv
    # （不经 wrapper/sudo），且 _execute_system_info 不走 _run_subprocess。
    # 安全依赖其"只读多命令聚合"性质，非全工具内核兜底。
    # wrapper 已删除 none 分支（洞1）：none 仅是 Python 侧的"不包裹"标记。
    "system.info": "none",
    "system.cpu_load": "readonly",
    "system.mem_usage": "readonly",
    "disk.usage": "readonly",
    "disk.large_files": "readonly",
    "process.list": "readonly",
    "network.ports": "readonly",
    "log.journal_query": "readonly",
    "log.large_log_scan": "readonly",
    "file.lsof_check": "readonly",
    "service.status": "readonly",
    "config.hash_snapshot": "readonly",
    "log.compress_rotate": "limited_write",
    "service.restart": "limited_write",
}


def get_sandbox_profile(tool_name: str) -> SandboxProfile:
    """返回工具的沙箱 profile；未注册默认 readonly（fail-closed）。"""
    return TOOL_SANDBOX_PROFILES.get(tool_name, "readonly")


def build_sandbox_argv(
    inner_argv: Sequence[str],
    profile: SandboxProfile,
    *,
    use_sudo: bool = False,
) -> list[str]:
    """构建经 wrapper 的沙箱 argv（纯函数，无 IO、无状态）。

    profile="none" → 原样返回 inner_argv 副本（不走 wrapper）。
    其他 profile → [sudo, --, wrapper, profile, --, *inner_argv]。
    安全属性不在此函数中——由 wrapper 硬编码（单一事实来源）。
    """
    if profile == "none":
        return list(inner_argv)
    argv: list[str] = []
    if use_sudo:
        argv.extend([SUDO_PATH, "--"])
    argv.extend([WRAPPER_PATH, profile, "--"])
    argv.extend(inner_argv)
    return argv


def is_sandbox_available() -> bool:
    """运行时检测：Linux + wrapper 存在 + systemd-run 可用。

    仅供 executor 构造期参考，不在 build_sandbox_argv 里调用（保持纯函数）。
    """
    if platform.system() != "Linux":
        return False
    return os.path.isfile(WRAPPER_PATH) and shutil.which("systemd-run") is not None
