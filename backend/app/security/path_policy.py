"""路径保护策略。

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
import re
from typing import Literal

from backend.app.contracts.tool import RiskLevel, ToolSpec
from backend.app.security.normalize import (
    has_dotdot,
    iter_abspath_values,
    normalize_path,
)
from backend.app.security.policy_rules import PolicySet, ProtectedPaths
from backend.app.security.risk_engine import risk_ge, rule_matches

PathDecision = Literal["allow", "confirm", "deny"]

# 变更类工具名称启发式（仅在拿不到 ToolSpec 时兜底，如 Executor 真实路径复核）；
# 有 spec 时以权威属性判定：risk >= R2 或 reversible=False 即变更类。
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
    """大小写敏感前缀比对（与 Linux 文件系统语义一致）。

    `base == "/"` 的特例**不是通配**：它只匹配根目录本身（`path == "/"`），
    绝不匹配"根下的一切"。这是刻意的——forbid_modify 里含 "/"，若按通配解释，
    任何绝对路径都会命中该条、所有变更类工具全被 deny，产品无法工作。
    "保护根目录本身"与"保护根下全部"是两件事，此处取前者；对具体子树的保护
    由清单里的其它条目（/etc、/usr、/var/lib/kylin-safeops …）逐条给出。
    """
    base_norm = canonicalize_linux_path(base)
    if base_norm == "/":
        return path == "/"
    return path == base_norm or path.startswith(base_norm.rstrip("/") + "/")


def _tool_is_change(tool_name: str, spec: ToolSpec | None = None) -> bool:
    if spec is not None:
        return risk_ge(spec.risk, "R2") or spec.reversible is False
    return tool_name in _CHANGE_TOOLS or any(h in tool_name for h in _DELETE_HINTS)


def _is_db_critical(path: str, protected: ProtectedPaths) -> bool:
    """判定路径是否触及关键数据库文件或审计日志（P1-12）。

    两条独立判据，任一命中即算：
    ① 落在 db_critical_dirs 下（数据目录，含国产库）；
    ② basename 或任一路径段命中 db_critical_names 的命名模式。

    ② 之所以不依赖父目录前缀：库日志常被部署到 /var/log/mysql/、/srv/backup/
    等目录，只按目录前缀判会漏——这正是 P1-12 报的那条
    /var/log/mysql/mysql-bin.000001 的成因。路径段（而非仅 basename）也参与
    匹配，是为了让 pg_wal/ 这类"目录名即语义"的模式对目录下的段文件同样生效。
    """
    for base in protected.db_critical_dirs:
        if _is_under(path, base):
            return True
    if not protected.db_critical_names:
        return False
    segments = [s for s in path.split("/") if s]
    return any(
        re.search(pattern, segment)
        for pattern in protected.db_critical_names
        for segment in segments
    )


def classify_paths(
    tool_name: str,
    args: dict,
    protected: ProtectedPaths,
    spec: ToolSpec | None = None,
) -> list[PathFinding]:
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
            findings.append(PathFinding(raw, raw, "deny", "R4", "PATH_TRAVERSAL", str(exc)))
            continue

        if path == "/":
            findings.append(
                PathFinding(
                    raw,
                    path,
                    "deny" if _tool_is_change(tool_name, spec) else "confirm",
                    "R4" if _tool_is_change(tool_name, spec) else "R2",
                    "PATH_ROOT",
                    "路径参数指向文件系统根，影响范围过大。",
                    "限定到具体子目录，并先做观测/ dry-run。",
                    None if _tool_is_change(tool_name, spec) else "operator",
                )
            )
            continue

        # forbid_modify：仅对变更类工具 deny；只读工具访问 /etc 等靠具体规则（FILE001 等）
        for base in protected.forbid_modify:
            if _tool_is_change(tool_name, spec) and _is_under(path, base):
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
            # forbid_delete：与 forbid_modify 对称，仅对变更类工具生效（D-6）；
            # 只读工具扫描 DB 数据目录不触发 admin confirm
            for base in protected.forbid_delete:
                if _tool_is_change(tool_name, spec) and _is_under(path, base):
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
                if _tool_is_change(tool_name, spec) and _is_db_critical(path, protected):
                    findings.append(
                        PathFinding(
                            raw,
                            path,
                            "confirm",
                            "R3",
                            "PATH_DB_CRITICAL",
                            f"路径 {path} 命中关键数据库/审计日志保护清单，需要管理员确认。",
                            "改用数据库原生的归档/清理命令，或通知 DBA 处置；"
                            "审计日志的留存调整须走审计留存策略，不要直接压缩。",
                            "admin",
                        )
                    )
                    continue
                for base in protected.rotate_only:
                    if _is_under(path, base) and _tool_is_change(tool_name, spec):
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


def real_path_violation(tool_name: str, real_path: str, policy: PolicySet) -> str | None:
    """对 realpath 解析后的真实路径重跑保护路径 + 参数级 deny 规则校验。

    供 Executor 在 symlink 解析改变路径时调用（判执一致兜底）：策略引擎在词法层
    裁决，从未见过真实目标；若真实目标命中保护路径（deny/confirm）或 FILE001 等
    参数级 deny 规则，必须拒绝执行——审批（若有）针对的是词法路径，不能迁移到
    一个策略层从未评估过的真实目标上。

    返回违规说明字符串（"<rule_id>: <reason>"）；无违规返回 None。
    """
    for finding in classify_paths(tool_name, {"path": real_path}, policy.protected_paths):
        if finding.decision in ("deny", "confirm"):
            return f"{finding.rule_id}: {finding.reason}"
    args = {"path": real_path}
    for rule in policy.rules:
        if rule.action != "deny" or rule.match.any_arg_matches is None:
            continue
        if rule_matches(rule, tool_name=tool_name, tool_risk="R0", args=args):
            return f"{rule.id}: {rule.reason}"
    return None
