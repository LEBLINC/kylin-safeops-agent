"""路径/参数归一化公共纯函数（security 层，evaluate 与 Executor 共用）。

★ 架构铁律：判定语义必须与执行语义逐字节一致。
本模块是"单一事实来源"——evaluate（策略引擎）和 Executor（执行器）import 同一份，
杜绝判执不一致 / TOCTOU。

归一化范围（best-effort 词法层）：
  - 只做 posixpath.normpath（消除冗余斜杠、解析 . 分量）。
  - 不做大小写归一（Linux 大小写敏感，/etc/PASSWD ≠ /etc/passwd）。
  - 不做全角→ASCII 转换（全角路径不是 Linux 路径，不应被误判为受保护路径）。
  - 不调 os.path.realpath / 不读文件系统（IO = 非确定性）。
  - symlink / 真实 canonicalize 兜底归 Executor + systemd 沙箱。

"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable

# 用于识别"形如绝对路径"的标量值：必须以 ASCII 斜杠 '/' 开头。
# 注意：全角斜杠（U+FF0F ／）不匹配，这正是我们要的——全角不是 Linux 路径。
_ABS_PATH_RE: re.Pattern[str] = re.compile(r"^/")


def normalize_path(raw: str) -> str:
    """词法归一化 Linux 绝对路径。

    只做 posixpath.normpath；不做大小写/全角/realpath 归一。
    调用方应确保 raw 已通过 _ABS_PATH_RE 检验（以 ASCII '/' 开头）。
    返回归一化后的路径字符串，最短为 "/"。
    """
    normed = posixpath.normpath(raw)
    return normed if normed else "/"


def has_dotdot(raw: str) -> bool:
    """词法层检查是否含 '..' 路径分量（用于二次防御，不依赖 realpath）。"""
    parts = raw.split("/")
    return ".." in parts


def iter_scalar_values(value: object) -> Iterable[str]:
    """递归展开任意嵌套结构（dict/list/tuple/set）的所有非 None 标量值为 str。

    用途：any_arg_matches 规则的扫描基础；evaluate 中无论嵌套多深都能命中危险串。
    """
    if isinstance(value, dict):
        for v in value.values():
            yield from iter_scalar_values(v)
    elif isinstance(value, list | tuple | set):
        for v in value:
            yield from iter_scalar_values(v)
    elif value is not None:
        yield str(value)


def iter_abspath_values(value: object) -> Iterable[str]:
    """递归展开所有"形如 ASCII 绝对路径（^/）"的标量值。

    ★ 这是路径保护的扫描基础（修正 L 指出的 D 项）：
      - 不认硬编码字段名（path/paths/...），改为识别"值形如绝对路径"的所有标量。
      - 全角斜杠不匹配，不会被误判为受保护路径。
      - 服务名（如 nginx.service）不以 '/' 开头，不会进入路径保护分支。
    每个命中值返回归一化后的路径（normalize_path）+ 原始值。
    """
    for s in iter_scalar_values(value):
        if _ABS_PATH_RE.match(s):
            yield s
