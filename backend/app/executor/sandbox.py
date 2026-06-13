"""systemd-run --scope 沙箱配置 + argv 构建纯函数（D，PR2b）。

铁律：
- build_sandbox_argv 是纯函数（无 IO / 无 state），返回 list[str]，绝不拼命令字符串。
- 命令仍只来自 COMMAND_TEMPLATES；systemd-run 是固定前缀，不是模板变量。
- profile 决定 systemd 安全属性强度：readonly（/ 只读）/ limited_write（放开写）/ none（不包裹）。
- 真沙箱验证待麒麟 VM；此文件仅负责 argv 构建正确性（O5 的内核级越权兜底设计）。
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass, field
from typing import Literal

#: 沙箱强度档位。
SandboxProfile = Literal["readonly", "limited_write", "none"]


@dataclass(frozen=True)
class SandboxConfig:
    """systemd-run --scope 沙箱配置。"""

    profile: SandboxProfile = "readonly"
    extra_properties: dict[str, str] = field(default_factory=dict)


#: 工具 → profile 映射（显式注册；未注册默认 readonly，保守 fail-closed）。
TOOL_SANDBOX_PROFILES: dict[str, SandboxProfile] = {
    "system.info": "none",  # 多命令聚合，executor 特殊处理
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
    """未注册工具默认 readonly（保守、fail-closed）。"""
    return TOOL_SANDBOX_PROFILES.get(tool_name, "readonly")


#: readonly：/ 只读挂载，最强约束。
_READONLY_PROPERTIES: dict[str, str] = {
    "ProtectSystem": "strict",  # / 只读挂载
    "ProtectHome": "yes",  # /home /root 不可见
    "PrivateTmp": "yes",  # 隔离 /tmp
    "NoNewPrivileges": "yes",  # 禁止提权
    "ProtectKernelTunables": "yes",
    "ProtectKernelModules": "yes",
    "ProtectControlGroups": "yes",
    "ReadOnlyPaths": "/",  # 冗余加固
}

#: limited_write：放开 ProtectSystem，允许写 /var/log（压缩）、/run/systemd（restart）。
_LIMITED_WRITE_PROPERTIES: dict[str, str] = {
    "ProtectHome": "yes",
    "PrivateTmp": "yes",
    "NoNewPrivileges": "yes",
    "ProtectKernelTunables": "yes",
    "ProtectKernelModules": "yes",
    "ProtectControlGroups": "yes",
    # 不加 ProtectSystem=strict / ReadOnlyPaths=/
}


def _properties_for_profile(profile: SandboxProfile) -> dict[str, str]:
    if profile == "readonly":
        return dict(_READONLY_PROPERTIES)
    if profile == "limited_write":
        return dict(_LIMITED_WRITE_PROPERTIES)
    return {}


#: systemd-run 绝对路径（麒麟 VM 验证后可调整）。
_SYSTEMD_RUN = "/usr/bin/systemd-run"
#: sudo 绝对路径。
_SUDO = "/usr/bin/sudo"


def build_sandbox_argv(
    inner_argv: list[str],
    profile: SandboxProfile,
    *,
    use_sudo: bool = False,
    extra_properties: dict[str, str] | None = None,
) -> list[str]:
    """将命令包裹在 systemd-run --scope 里。

    profile="none" → 直接返回 inner_argv 的副本（不包裹）。
    use_sudo=True → 前置 sudo（Agent 以非 root 用户运行时需要）。
    纯函数：无 IO、无状态，方便测试。argv 全是独立字符串，绝不字符串拼接。
    """
    if profile == "none":
        return list(inner_argv)

    props = _properties_for_profile(profile)
    if extra_properties:
        props.update(extra_properties)

    argv: list[str] = []
    if use_sudo:
        argv.extend([_SUDO, "--"])
    argv.extend([_SYSTEMD_RUN, "--scope", "--quiet"])
    for key, value in props.items():
        argv.extend(["-p", f"{key}={value}"])
    argv.append("--")
    argv.extend(inner_argv)
    return argv


def is_sandbox_available() -> bool:
    """运行时检测：Linux + systemd-run 可执行。

    仅供 executor 构造期参考，不在 build_sandbox_argv 里调用（保持纯函数）。
    """
    if platform.system() == "Windows":
        return False
    return shutil.which(_SYSTEMD_RUN) is not None
