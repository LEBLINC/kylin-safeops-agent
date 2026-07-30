"""P0-8: 六份交付文档引用的每一张图都必须随包入库。

修前 .gitignore 只放行 README 内嵌的 2 张，77 处引用里 75 处进不了源码包
→ 读者拿到的包中六份交付文档满屏破图，而缺的正是 VM 实测与性能证据截图。

本用例的解析逻辑刻意做成"通用 markdown 图片引用"，不按目录写死：
上一版只匹配 ../figures/，把 56 处 ../screenshots/ 整个漏掉，用例照常全绿——
按目录枚举的断言只能证明"我想到的那些没缺"，证明不了"没有我没想到的"。

  G-1 交付文档引用的每张图都已入库（untracked = 0），不限目录
  G-2 引用同时覆盖 figures 与 screenshots 两类（防解析逻辑退回单目录后假绿）
  G-3 figures/src/（.mmd 源 + 字体）仍不入库——中间产物，读者不需要
  G-4 git archive 产物确实带上这些图（不是只在工作树里）
  G-5 未被任何文档引用的截图不入库（交付面不混进无出处的图）
"""

from __future__ import annotations

import pathlib
import re
import subprocess

_REPO = pathlib.Path(__file__).resolve().parents[3]
_DELIVERY_DOCS = sorted((_REPO / "docs" / "v2").glob("软件*.md"))

# 与验收脚本 grep -ohE '!\[[^]]*\]\([^)]+\)' 等价：任意 markdown 图片引用，
# 不预设目录名，新增图片目录时无需改用例即可纳入。
_IMG_REF = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _referenced_images() -> set[str]:
    """解析六份交付文档的图片引用，归一化为仓库相对路径。

    文档内写法为 ../figures/x.png / ../screenshots/y.png（相对 docs/v2/），
    统一还原成 docs/... 以便直接喂给 git ls-files。
    """
    refs: set[str] = set()
    for doc in _DELIVERY_DOCS:
        for raw in _IMG_REF.findall(doc.read_text(encoding="utf-8")):
            target = raw.split()[0].strip()  # 去掉 ![](path "title") 的 title
            if target.startswith("http://") or target.startswith("https://"):
                continue
            refs.add(f"docs/{target[3:]}" if target.startswith("../") else target)
    return refs


def _tracked(paths: list[str]) -> set[str]:
    if not paths:
        return set()
    out = subprocess.run(
        ["git", "ls-files", "--", *paths],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {ln.strip() for ln in out.splitlines() if ln.strip()}


def test_g1_all_referenced_images_tracked() -> None:
    """G-1: 引用的图一张都不能缺——缺一张读者就看到一个破图。"""
    refs = _referenced_images()
    assert len(_DELIVERY_DOCS) == 6, f"用例前提：应有 6 份交付文档，实际 {len(_DELIVERY_DOCS)}"
    assert refs, "G-1: 未从交付文档解析出图片引用（用例前提失效）"

    missing = sorted(refs - _tracked(sorted(refs)))
    assert not missing, f"G-1: {len(missing)} 张被引用的图未入库（源码包内是破图）：{missing[:5]}"


def test_g2_both_image_dirs_covered() -> None:
    """G-2: 两类图都得被解析到。

    单看 G-1 无法区分"全都在库"和"解析器没看见"——上一版正是后者。
    这里钉住解析结果必须同时含两个目录，解析逻辑一旦退回单目录立刻红。
    """
    dirs = {r.rsplit("/", 1)[0] for r in _referenced_images()}
    for expected in ("docs/figures", "docs/screenshots"):
        assert expected in dirs, f"G-2: 未解析到 {expected} 的引用，解析逻辑可能漏了整类图"


def test_g3_figure_sources_not_tracked() -> None:
    """G-3: .mmd 源与字体不入库——它们是重新生成图片的中间产物。"""
    assert not _tracked(["docs/figures/src"]), "G-3: figures/src/ 不应入库"


def test_g4_git_archive_contains_images() -> None:
    """G-4: 发布产物带图数与已入库图数一致，而非只在工作树可见。

    比对对象是"索引里已入库的图"而非"文档引用的图"——本用例验的是
    "入库的东西确实进得了发布产物"，G-1 已负责"引用的都已入库"。
    这样本次改动尚未 commit 时（HEAD 还是旧状态）本用例仍是有意义的
    等值断言，不会因时序假红。
    """
    archive = subprocess.run(
        ["git", "archive", "HEAD"], cwd=_REPO, capture_output=True, check=True
    ).stdout
    listing = subprocess.run(
        ["tar", "-t"], input=archive, capture_output=True, check=True
    ).stdout.decode("utf-8", "replace")
    in_archive = {ln.strip() for ln in listing.splitlines() if ln.strip().endswith(".png")}

    head_tracked = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", "docs/figures", "docs/screenshots"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    head_images = {ln.strip() for ln in head_tracked.splitlines() if ln.strip().endswith(".png")}

    assert (
        head_images <= in_archive
    ), f"G-4: HEAD 已入库但发布产物缺失：{sorted(head_images - in_archive)[:5]}"


def test_g5_unreferenced_screenshots_not_tracked() -> None:
    """G-5: 没有任何文档引用的截图不该进交付面。

    截图目录里存着改名前的副本和备选打码版；放行规则若写成整目录通配，
    这些无出处的图会一并进包。此处反向钉住：入库集合 ⊆ 被引用集合。
    """
    tracked = _tracked(["docs/screenshots"])
    assert tracked, "G-5: 用例前提失效——screenshots 一张都没入库"

    stray = sorted(tracked - _referenced_images())
    assert not stray, f"G-5: {len(stray)} 张未被引用的截图混进了交付包：{stray[:5]}"
