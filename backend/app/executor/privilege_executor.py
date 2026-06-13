"""特权执行器（D）— subprocess list 框架 + systemd 瞬态 service 沙箱（PR2b-v2）。

铁律：
- 绝不 shell=True；绝不拼命令字符串。
- 路径归一：import security/normalize.py 同一份（与 evaluate 同源，判执逐字节一致）。
  evaluate 做词法层（posixpath.normpath）；Executor 在词法层之上再做 Linux os.path.realpath
  兜底，解析 symlink（D-1b），消除 TOCTOU 漏洞。
- 执行失败 = exit_code != 0 正常 return（方案 B）；只有系统级故障才 raise。
- stdout 截断 8KB；stderr 追加 "--- stderr ---"。
- ToolResult.is_untrusted=True。

沙箱（PR2b-v2）：
- sandbox_enabled=True 时，命令经 deploy/sandbox/kylin-safeops-run.sh wrapper 执行；
  wrapper 内部以 systemd-run 瞬态 service（--pipe --wait --collect --quiet，非 --scope）
  施加保护属性（ProtectSystem/ReadOnlyPaths/ProtectHome/PrivateTmp/NoNewPrivileges/...）。
  采用瞬态 service 而非 scope 是关键：scope 不经 fork/exec，Protect* 会被静默忽略。
- 安全属性唯一事实来源在 wrapper；Python 仅选 profile + 拼 wrapper argv（sandbox.py）。
- sandbox_enabled=False（默认）时行为与首版完全一致（无沙箱），现有测试零回归。
- Windows 上无论设置如何均不包裹。Linux+systemd 环境下集成测试真验证写拒绝；
  麒麟 V11 待验证 LoongArch 特有项（systemd-run 绝对路径 / dbus 可达性等）。
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
from collections.abc import Sequence

from backend.app.contracts.intent import CandidateTool
from backend.app.contracts.untrusted import ToolResult
from backend.app.executor.command_templates import (
    DEFAULT_VARIANT,
    CommandTemplate,
    available_variants,
    get_template,
    has_tool,
)
from backend.app.executor.sandbox import build_sandbox_argv, get_sandbox_profile
from backend.app.security.normalize import has_dotdot, normalize_path
from backend.app.security.path_policy import real_path_violation
from backend.app.security.policy_loader import DEFAULT_POLICY
from backend.app.security.policy_rules import PolicySet
from mcp_servers.os_ops.fallback import candidate_commands

#: stdout + stderr 截断上限（字节）。
MAX_OUTPUT_BYTES = 8 * 1024
#: 默认命令超时（秒）。
DEFAULT_TIMEOUT = 30
#: 安全 CWD（Linux）。
SAFE_CWD = "/" if platform.system() != "Windows" else os.environ.get("SYSTEMROOT", "C:\\")
#: 安全环境变量（最小集）。
SAFE_ENV: dict[str, str] = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
}


class PrivilegeExecutor:
    """D 的 Executor 首版：subprocess list + 命令模板白名单。

    构造无状态依赖；execute() 可并发调用（每次独立子进程）。
    policy 仅用于 symlink 解析后对真实路径重跑保护路径校验（与 evaluate 同一份配置）。
    """

    def __init__(
        self,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        policy: PolicySet = DEFAULT_POLICY,
        sandbox_enabled: bool = False,
    ) -> None:
        self._timeout = timeout
        self._policy = policy
        self._sandbox_enabled = sandbox_enabled

    async def execute(self, tool: CandidateTool) -> ToolResult:
        """执行单个工具调用。"""
        # 1. 模板白名单拦截
        if not has_tool(tool.name):
            return self._fail(tool, 127, f"<tool-not-in-whitelist: {tool.name}>")

        # 2. system.info 特殊处理：多命令聚合
        if tool.name == "system.info":
            return await self._execute_system_info(tool)

        # 3. 选择命令变体（fallback 探测）
        try:
            argv = self._resolve_argv(tool)
        except _PathTraversalError as exc:
            return self._fail(tool, 1, str(exc))
        if argv is None:
            names = candidate_commands(tool.name) or available_variants(tool.name)
            return self._fail(tool, 127, f"<command-not-available: {'/'.join(names)}>")

        # 4. 执行
        return await self._run_subprocess(tool, argv)

    # ---- 内部方法 ---------------------------------------------------------

    def _resolve_argv(self, tool: CandidateTool) -> list[str] | None:
        """解析命令模板 + fallback 探测 + 参数注入，返回完整 argv。"""
        # 有 fallback 声明：按候选探测
        candidates = candidate_commands(tool.name)
        if candidates:
            for cmd in candidates:
                if shutil.which(cmd) is not None:
                    tpl = get_template(tool.name, cmd)
                    if tpl is not None:
                        return self._build_argv(tpl, tool)
            return None  # 全缺失

        # 无 fallback 声明：用默认变体
        tpl = get_template(tool.name, DEFAULT_VARIANT)
        if tpl is None:
            return None
        return self._build_argv(tpl, tool)

    def _build_argv(self, tpl: CommandTemplate, tool: CandidateTool) -> list[str]:
        """从模板 + args 构建安全 argv。"""
        argv = list(tpl.argv_prefix)
        args = tool.args

        # 动态参数：按序追加为独立 argv（不拼进字符串）
        for key in tpl.dynamic_args:
            val = args.get(key)
            if val is None:
                continue
            if isinstance(val, list):
                for item in val:
                    argv.append(self._sanitize_arg(str(item), tool.name))
            else:
                argv.append(self._sanitize_arg(str(val), tool.name))

        # flag 映射：-u <unit> -p <priority> ...
        for arg_key, flag in tpl.flag_map.items():
            val = args.get(arg_key)
            if val is not None and str(val):
                argv.extend([flag, self._sanitize_arg(str(val), tool.name)])

        # 工具特殊 argv 补全
        argv = self._tool_specific_argv(tool.name, argv, args)
        return argv

    def _sanitize_arg(self, value: str, tool_name: str) -> str:
        """参数安全校验：与 evaluate 同源归一（D-1a）+ Linux realpath symlink 兜底（D-1b）。

        词法层：复用 security/normalize.normalize_path（与 evaluate 同一份，判执逐字节一致）。
        Linux 兜底：os.path.realpath 解析 symlink；若解析结果与词法路径不同（symlink/`.`
        改变了目标），对【真实路径】重跑保护路径 + deny 规则校验（real_path_violation，
        与 evaluate 同一份 path_policy 逻辑）；命中即拒绝执行——策略层从未见过该目标，
        不能让 /tmp/link → /etc/shadow 穿越词法裁决（判定语义 == 执行语义）。
          NOTE(symlink): evaluate 是纯词法层（无 IO，确定性铁律），realpath 只在 Executor
          执行层做，与 evaluate 职责分离，符合 §工作策略.md §2 架构设计。
        """
        if has_dotdot(value):
            raise _PathTraversalError(f"'..' path traversal in arg: {value}")
        if value.startswith("/"):
            normed = normalize_path(value)  # 词法层：与 evaluate 共用同一份
            if platform.system() != "Windows":  # Linux：真实 symlink 兜底
                real = os.path.realpath(normed)
                if has_dotdot(real):
                    raise _PathTraversalError(f"realpath traversal detected: {real}")
                if real != normed:
                    violation = real_path_violation(tool_name, real, self._policy)
                    if violation is not None:
                        raise _PathTraversalError(
                            f"symlink target violates protection: "
                            f"{value} -> {real} ({violation})"
                        )
                return real
            return normed
        return value

    def _tool_specific_argv(self, tool_name: str, argv: list[str], args: dict) -> list[str]:
        """工具特殊参数补全。"""
        if tool_name == "disk.large_files":
            return [*argv, "-type", "f", "-printf", "%s\\t%p\\n"]
        if tool_name == "log.large_log_scan":
            return [*argv, "-type", "f", "-name", "*.log", "-printf", "%s\\t%p\\n"]
        if tool_name == "file.lsof_check":
            pid = args.get("pid")
            if pid is not None:
                return ["/usr/sbin/lsof", "-p", str(int(pid))]
            return [*argv, "--"]
        return argv

    async def _run_subprocess(self, tool: CandidateTool, argv: Sequence[str]) -> ToolResult:
        """在子进程中执行命令（不用 shell）。

        sandbox_enabled=True 且非 Windows 时，经 wrapper（systemd 瞬态 service）包裹；
        包裹在路径校验（_sanitize_arg）之后进行，沙箱不改变判执语义。
        """
        final_argv = list(argv)
        if self._sandbox_enabled and platform.system() != "Windows":
            profile = get_sandbox_profile(tool.name)
            use_sudo = os.geteuid() != 0 if hasattr(os, "geteuid") else False
            final_argv = build_sandbox_argv(final_argv, profile, use_sudo=use_sudo)

        try:
            proc = await asyncio.create_subprocess_exec(
                *final_argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=SAFE_CWD,
                env=SAFE_ENV,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            return self._fail(tool, 124, f"<timeout after {self._timeout}s>")
        except FileNotFoundError:
            cmd_name = argv[0] if argv else "?"
            return self._fail(tool, 127, f"<command-not-found: {cmd_name}>")
        except OSError as exc:
            # 系统级故障（权限/沙箱等）→ raise，由 orchestrator 转 error 事件
            raise RuntimeError(f"executor OS error for {tool.name}: {exc}") from exc

        stdout_text = self._truncate(stdout_bytes)
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        if stderr_text:
            stdout_text += f"\n--- stderr ---\n{stderr_text}"

        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=proc.returncode or 0,
            stdout_truncated=stdout_text,
            is_untrusted=True,
        )

    async def _execute_system_info(self, tool: CandidateTool) -> ToolResult:
        """system.info: 多命令聚合，stdout 用 JSON 字符串。"""
        cmds: dict[str, list[str]] = {
            "hostname": ["/usr/bin/hostname"],
            "os_release": ["/usr/bin/cat", "/etc/os-release"],
            "kernel": ["/usr/bin/uname", "-r"],
            "arch": ["/usr/bin/uname", "-m"],
            "uptime": ["/usr/bin/uptime", "-p"],
            "boot_time": ["/usr/bin/who", "-b"],
        }
        results: dict[str, str] = {}
        for key, argv in cmds.items():
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    cwd=SAFE_CWD,
                    env=SAFE_ENV,
                )
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                results[key] = out.decode("utf-8", errors="replace").strip()
            except Exception:  # noqa: BLE001
                results[key] = ""
        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=0,
            stdout_truncated=json.dumps(results, ensure_ascii=False),
            is_untrusted=True,
        )

    def _truncate(self, raw: bytes) -> str:
        """截断 stdout 至 MAX_OUTPUT_BYTES 并标注。"""
        text = raw.decode("utf-8", errors="replace")
        if len(raw) <= MAX_OUTPUT_BYTES:
            return text.strip()
        truncated = raw[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        overflow = len(raw) - MAX_OUTPUT_BYTES
        return f"{truncated.strip()}\n... [truncated {overflow} bytes]"

    @staticmethod
    def _fail(tool: CandidateTool, code: int, msg: str) -> ToolResult:
        """构造失败 ToolResult（方案 B：正常 return，不 raise）。"""
        return ToolResult(
            tool=tool.name,
            args=tool.args,
            exit_code=code,
            stdout_truncated=msg,
            is_untrusted=True,
        )


class _PathTraversalError(ValueError):
    """路径 '..' 逃逸。由 executor 内部 _sanitize_arg 抛出，_run 捕获后转方案 B。"""
