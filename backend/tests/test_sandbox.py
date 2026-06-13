"""沙箱 argv 构建测试（D，PR2b）。

验证 build_sandbox_argv 纯函数：
- 三档 profile 的安全属性正确
- profile=none 不包裹
- sudo 前置
- extra_properties 追加
- 全部 argv 无 shell 元字符
- 每个命令模板都有 profile 映射
"""

from __future__ import annotations

from backend.app.executor.command_templates import COMMAND_TEMPLATES
from backend.app.executor.sandbox import (
    TOOL_SANDBOX_PROFILES,
    build_sandbox_argv,
    get_sandbox_profile,
)

_INNER = ["/usr/bin/df", "-PB1"]


def test_build_sandbox_argv_readonly() -> None:
    """readonly：含 --scope --quiet + 所有 readonly 安全属性 + 末尾原命令。"""
    argv = build_sandbox_argv(_INNER, "readonly")
    assert "/usr/bin/systemd-run" in argv
    assert "--scope" in argv
    assert "--quiet" in argv
    joined = argv[argv.index("--scope") :]
    assert "ProtectSystem=strict" in joined
    assert "ProtectHome=yes" in joined
    assert "PrivateTmp=yes" in joined
    assert "NoNewPrivileges=yes" in joined
    assert "ReadOnlyPaths=/" in joined
    # 原命令在最后一个 -- 之后原样保留
    assert argv[-2:] == _INNER


def test_build_sandbox_argv_limited_write() -> None:
    """limited_write：不含 ProtectSystem=strict / ReadOnlyPaths=/，但含基线属性。"""
    argv = build_sandbox_argv(_INNER, "limited_write")
    assert "ProtectSystem=strict" not in argv
    assert "ReadOnlyPaths=/" not in argv
    assert "NoNewPrivileges=yes" in argv
    assert "PrivateTmp=yes" in argv


def test_build_sandbox_argv_none() -> None:
    """profile=none：直接返回 inner_argv 副本，长度不变。"""
    argv = build_sandbox_argv(_INNER, "none")
    assert argv == _INNER
    assert argv is not _INNER  # 返回副本，不复用入参


def test_build_sandbox_argv_extra_properties() -> None:
    """extra_properties 追加到基线属性（以 -p Key=Value 形式出现）。"""
    argv = build_sandbox_argv(_INNER, "readonly", extra_properties={"MemoryMax": "256M"})
    assert "MemoryMax=256M" in argv


def test_build_sandbox_argv_with_sudo() -> None:
    """use_sudo=True：argv 以 sudo 开头，且 sudo 后紧跟 --。"""
    argv = build_sandbox_argv(_INNER, "readonly", use_sudo=True)
    assert argv[0] == "/usr/bin/sudo"
    assert argv[1] == "--"
    assert argv[2] == "/usr/bin/systemd-run"


def test_build_sandbox_argv_without_sudo() -> None:
    """use_sudo=False（默认）：argv 不含 sudo，首项即 systemd-run。"""
    argv = build_sandbox_argv(_INNER, "readonly")
    assert "/usr/bin/sudo" not in argv
    assert argv[0] == "/usr/bin/systemd-run"


def test_all_templates_have_sandbox_profile() -> None:
    """COMMAND_TEMPLATES 里每个工具都在 TOOL_SANDBOX_PROFILES 显式注册。"""
    for tool_name in COMMAND_TEMPLATES:
        assert tool_name in TOOL_SANDBOX_PROFILES, f"{tool_name} 缺 sandbox profile"


def test_unknown_tool_defaults_readonly() -> None:
    """未注册工具默认 readonly（fail-closed）。"""
    assert get_sandbox_profile("ghost.tool") == "readonly"


def test_argv_no_shell_metachar() -> None:
    """每项 argv 都是独立字符串，绝不含 shell 元字符（无字符串拼接）。"""
    argv = build_sandbox_argv(_INNER, "readonly", use_sudo=True)
    metachars = [";", "|", "&", "$(", "`", ">", "<", "&&"]
    for item in argv:
        for mc in metachars:
            assert mc not in item, f"argv 项 {item!r} 含 shell 元字符 {mc!r}"


def test_readonly_has_protect_system_strict() -> None:
    assert "ProtectSystem=strict" in build_sandbox_argv(_INNER, "readonly")


def test_limited_write_no_protect_system_strict() -> None:
    assert "ProtectSystem=strict" not in build_sandbox_argv(_INNER, "limited_write")


def test_build_is_pure_function() -> None:
    """同输入 50 次调用结果完全相等（纯函数，无状态）。"""
    results = [
        build_sandbox_argv(_INNER, "readonly", use_sudo=True, extra_properties={"X": "y"})
        for _ in range(50)
    ]
    first = results[0]
    assert all(r == first for r in results)


def test_known_tool_profiles() -> None:
    """关键工具 profile 归类正确：只读类 readonly，变更类 limited_write，聚合类 none。"""
    assert get_sandbox_profile("disk.usage") == "readonly"
    assert get_sandbox_profile("service.restart") == "limited_write"
    assert get_sandbox_profile("log.compress_rotate") == "limited_write"
    assert get_sandbox_profile("system.info") == "none"
