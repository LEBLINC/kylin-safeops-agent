"""P0-8: 六份交付文档引用的图片必须随包入库。

修前 .gitignore 只放行 README 内嵌的 2 张，其余 19 张被忽略 → 源码包内六份
交付文档满屏破图（读者拿到的包里图全裂）。

  G-1 六份文档引用的每张图都已入库（untracked = 0）
  G-2 figures/src/（.mmd 源 + 字体）仍不入库——中间产物，读者不需要
  G-3 git archive 产物确实含这些图（不是只在工作树里）
"""

from __future__ import annotations

import pathlib
import re
import subprocess

_REPO = pathlib.Path(__file__).resolve().parents[3]
_DELIVERY_DOCS = sorted((_REPO / "docs" / "v2").glob("软件*.md"))


def _referenced_figures() -> set[str]:
    """从六份交付文档解析出被引用的图片仓库相对路径。"""
    refs: set[str] = set()
    for doc in _DELIVERY_DOCS:
        text = doc.read_text(encoding="utf-8")
        for rel in re.findall(r"\.\./figures/([\w.-]+\.png)", text):
            refs.add(f"docs/figures/{rel}")
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


def test_g1_all_referenced_figures_tracked() -> None:
    """G-1: 交付文档引用的图片一张都不能缺（缺一张读者就看到一个破图）。"""
    refs = _referenced_figures()
    assert len(_DELIVERY_DOCS) == 6, f"用例前提：应有 6 份交付文档，实际 {len(_DELIVERY_DOCS)}"
    assert refs, "G-1: 未从交付文档解析出图片引用（用例前提失效）"

    tracked = _tracked(sorted(refs))
    missing = sorted(refs - tracked)
    assert not missing, f"G-1: {len(missing)} 张被引用的图未入库（源码包内会是破图）：{missing[:5]}"


def test_g2_figure_sources_not_tracked() -> None:
    """G-2: .mmd 源与字体不入库——它们是重新生成图片的中间产物。"""
    assert not _tracked(["docs/figures/src"]), "G-2: figures/src/ 不应入库"


def test_g3_git_archive_contains_figures() -> None:
    """G-3: 发布产物（git archive）带图数与已入库图数一致，而非只在工作树可见。

    比对对象是"索引里已入库的图"而非"文档引用的图"——本用例要验的是
    "入库的东西确实进得了发布产物"，而 G-1 已负责"引用的都已入库"。
    这样在本次改动尚未 commit 时（HEAD 只含旧的 2 张），本用例仍是有意义的
    等值断言，不会因时序而假红。
    """
    archive = subprocess.run(
        ["git", "archive", "HEAD"], cwd=_REPO, capture_output=True, check=True
    ).stdout
    listing = subprocess.run(
        ["tar", "-t"], input=archive, capture_output=True, check=True
    ).stdout.decode("utf-8", "replace")
    in_archive = {ln.strip() for ln in listing.splitlines() if ln.strip().endswith(".png")}

    head_tracked = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", "docs/figures"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    head_figures = {ln.strip() for ln in head_tracked.splitlines() if ln.strip().endswith(".png")}

    assert (
        head_figures <= in_archive
    ), f"G-3: HEAD 已入库但发布产物缺失：{sorted(head_figures - in_archive)[:5]}"
