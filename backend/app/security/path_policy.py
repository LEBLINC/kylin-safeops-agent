"""路径保护策略（D）。

策略引擎路径判定层（词法层，best-effort）。共用 normalize.py 纯函数，保证判执一致。

关键约定（与执行层逐字节一致）：
  - 路径归一只做 normalize_path（posixpath.normpath），不做大小写/全角归一。
  - 路径保护扫描所有"形如 ^/ 绝对路径"的参数值，不认硬编码字段名（修正 D）。
  - 大小写敏感比对：/etc/PASSWD ≠ /etc/passwd（修正 A）。
  - 全角斜杠不被识别为绝对路径（修正 B）。
  - forbid_modify 对**变更类**工具生效；/etc/shadow 等只读工具靠 FILE001 规则（修正 精度）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.app.contracts.tool import RiskLevel
from backend.app.security.policy_rules import ProtectedPaths
from backend.app.security.normalize import (
    has_dotdot,
    iter_abspath_values,
    normalize_path,
)

PathDecision = Literal["allow", "confirm", "deny"]

# 变更类工具集：这些工具对 forbid_modify 路径执行写/删操作，触发 deny。
# 只读工具（disk.large_files、file.lsof_check 等）对 /etc 扫描不触发 forbid_modify deny。
_CHANGE_TOOLS = {"log.compress_rotate", "service.restart"}
_DELETE_HINTS = {"delete", "remove", "clean", "truncate", "wipe"}


@dataclass(frozen=True)
class PathFinding:
    """单个路径参数的裁决发现。"""

    original: str
    canonical: str
    decision: PathDecision
    risk: RiskLevel
    rule_id: str
    reason: str
    safer_alternative: str | None = None
    approval_role: str | None = None


def canonicalize_linux_path(raw: str) -> str:
    """词法归一化 Linux 绝对路径（向后兼容包装，内部委托 normalize.normalize_path）。

    schema_validator 已拦截 '..'，这里二次校验（防御纵深）。不做大小写/全角归一。
    """
    if not raw.startswith("/"):
        raise ValueError(f"path must be absolute (got {raw!r})")
    if has_dotdot(raw):
        raise ValueError(f"'..' path traversal is forbidden (got {raw!r})")
    return normalize_path(raw)


def _is_under(path: str, base: str) -> bool:
    """大小写敏感前缀比对（与 Linux 文件系统语义一致）。"""
    base_norm = canonicalize_linux_path(base)
    if base_norm == "/":
        return path == "/"
    return path == base_norm or path.startswith(base_norm.rstrip("/") + "/")


def _tool_is_change(tool_name: str) -> bool:
    return tool_name in _CHANGE_TOOLS or any(h in tool_name for h in _DELETE_HINTS)


def classify_paths(tool_name: str, args: dict, protected: ProtectedPaths) -> list[PathFinding]:
    """按保护清单分类所有"形如绝对路径"的参数值（修正 D：不认硬编码字段名）。

    扫描方式：递归遍历 args 的所有标量值，凡以 ASCII '/' 开头的均视为路径候选。
    大小写敏感比对（修正 A）；全角斜杠不触发（修正 B）。
    forbid_modify 仅对变更类工具生效（修正 精度）。
    """
    findings: list[PathFinding] = []
    seen_raw: set[str] = set()  # 去重，同一路径值不重复生成 Finding
    for raw in iter_abspath_values(args):
        if raw in seen_raw:
            continue
        seen_raw.add(raw)
        try:
            path = canonicalize_linux_path(raw)
        except ValueError as exc:
            findings.append(
                PathFinding(raw, raw, "deny", "R4", "PATH_TRAVERSAL", str(exc))
            )
            continue

        if path == "/":
            findings.append(
                PathFinding(
                    raw,
                    path,
                    "deny" if _tool_is_change(tool_name) else "confirm",
                    "R4" if _tool_is_change(tool_name) else "R2",
                    "PATH_ROOT",
                    "路径参数指向文件系统根，影响范围过大。",
                    "限定到具体子目录，并先做观测/ dry-run。",
                    None if _tool_is_change(tool_name) else "operator",
                )
            )
            continue

        # forbid_modify：仅对变更类工具 deny；只读工具访问 /etc 等靠具体规则（FILE001 等）
        for base in protected.forbid_modify:
            if _tool_is_change(tool_name) and _is_under(path, base):
                findings.append(
                    PathFinding(
                        raw,
                        path,
                        "deny",
                        "R4",
                        "PATH_FORBID_MODIFY",
                        f"路径 {path} 位于受保护系统路径 {base} 下，禁止操作。",
                    )
                )
                break
        else:
            for base in protected.forbid_delete:
                if _is_under(path, base):
                    findings.append(
                        PathFinding(
                            raw,
                            path,
                            "confirm",
                            "R3",
                            "PATH_DB_PROTECTED",
                            f"路径 {path} 位于数据库数据目录 {base} 下，需要管理员确认。",
                            "优先使用数据库原生命令或通知 DBA 处置。",
                            "admin",
                        )
                    )
                    break
            else:
                for base in protected.rotate_only:
                    if _is_under(path, base) and _tool_is_change(tool_name):
                        findings.append(
                            PathFinding(
                                raw,
                                path,
                                "confirm",
                                "R2",
                                "PATH_ROTATE_ONLY",
                                f"路径 {path} 位于日志目录 {base}，只允许压缩/轮转类处置。",
                                "使用 log.compress_rotate，不直接删除。",
                                "operator",
                            )
                        )
                        break
                else:
                    for base in protected.confirm_required:
                        if _is_under(path, base):
                            findings.append(
                                PathFinding(
                                    raw,
                                    path,
                                    "confirm",
                                    "R2",
                                    "PATH_CONFIRM_REQUIRED",
                                    f"路径 {path} 需要人工确认。",
                                    approval_role="operator",
                                )
                            )
                            break
    return findings
