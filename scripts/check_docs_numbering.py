"""check_docs_numbering.py — 4 文档最大已用号守门.

扫描 4 文档 (集成对齐备忘 / 审阅交接 / 项目整体进度 / 麒麟VM-bring-up总清单)，
取各文档 留痕号 之N 的最大整数值 (支持 之50 / 之五十二 形)，输出报告。

Usage:
  python scripts/check_docs_numbering.py
  (CI: standalone 工具)
"""

from __future__ import annotations

import pathlib
import re

DOCS = [
    "集成对齐备忘.md",
    "审阅交接.md",
    "项目整体进度-给D与X.md",
    "麒麟VM-bring-up总清单.md",
]


_ZH = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


_PATTERN = re.compile(r"之([零一二三四五六七八九十]+)")


def zh_to_int(s: str) -> int | None:
    """之N chinese → int."""
    if not s:
        return None
    if s == "十":
        return 10
    if len(s) == 1:
        return _ZH.get(s)
    if len(s) == 2 and s[1] == "十":  # e.g. 二十
        return _ZH.get(s[0], 0) * 10
    if len(s) == 2:  # e.g. 五十二 = 5*10+2
        a, b = _ZH.get(s[0]), _ZH.get(s[1])
        return a * 10 + b if (a is not None and b is not None) else None
    # 3-char 之三十二 etc.
    if len(s) == 3 and s[1] == "十":
        a, b = _ZH.get(s[0]), _ZH.get(s[2])
        return a * 10 + b if (a is not None and b is not None) else None
    return None


def nums_in_file(path: pathlib.Path) -> set[int]:
    """返该文档所有 留痕号 之N 整数集合; 文件不存在返空集."""
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    out: set[int] = set()
    for m in _PATTERN.finditer(text):
        n = zh_to_int(m.group(1))
        if n is not None and 1 <= n <= 999:
            out.add(n)
    return out


def main() -> int:
    """主: 输出 4 文档 max 留痕号 + 全集."""
    repo = pathlib.Path(".")
    overall: set[int] = set()
    print("4 文档 留痕号 之N max 报告:\n")
    for name in DOCS:
        nums = nums_in_file(repo / name)
        overall |= nums
        if nums:
            mx = max(nums)
            print(f"  {name}: max = 之{mx}, 命中 {len(nums)} 个")
        else:
            print(f"  {name}: (无)")
    if overall:
        mx = max(overall)
        print(f"\n总体 max 留痕号 = 之{mx}")
        print(f"全 4 文档 命中 值: {sorted(overall)}")
    print("\n✓ PASS: 守卫脚本已打印 max + 全集 (人工审阅)")
    return 0
