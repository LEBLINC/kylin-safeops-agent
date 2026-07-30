"""P0-7: 交付部署文档与实装一致性（可脚本化验收）。

修前该文档 14 处与实装相反——照它做必然装不成：
  - 以已删除的 `deploy/kylin-safeops.service` 为准并标"✅ 采用"
  - 给该已删文件的 SHA256（永远校验不过）
  - 卸载章节卸错文件名
  - 指示"删除 http2 on; 一行"（R-1 后该行已不存在）
  - 引用已改名的 ldap.env（R-3 后是 agent.env）

评委按文档实操即卡死，故本用例把三条可机检的规则钉死：
  D-1 文档提及的仓库内文件路径必须真实存在
  D-2 "删除/改写某行"类指令引用的字符串必须在目标文件中可定位
  D-3 给出 SHA256 的文件必须存在且摘要一致（否则应删除该校验行）
  D-4 env 变量表须覆盖实际生效的关键变量且默认值正确
"""

from __future__ import annotations

import hashlib
import pathlib
import re

_REPO = pathlib.Path(__file__).resolve().parents[3]
_DOC = _REPO / "docs" / "v2" / "软件安装包及部署文档.md"


def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_d1_referenced_repo_paths_exist() -> None:
    """D-1: 文档提及的 deploy/ 内文件路径必须真实存在。"""
    text = _doc()
    # 只取形如 deploy/xxx.ext 的仓库内路径（排除 /etc、/opt 等目标机路径）
    refs = set(re.findall(r"`(deploy/[\w./-]+\.(?:service|sh|conf|py|example))`", text))
    assert refs, "D-1: 未从文档解析出 deploy/ 路径（用例前提失效）"
    missing = sorted(r for r in refs if not (_REPO / r).exists())
    assert not missing, f"D-1: 文档引用了不存在的文件（照做必失败）：{missing}"


def test_d2_edit_instructions_are_locatable() -> None:
    """D-2: "删除/改为某行"类指令引用的目标串须在对应文件中可定位。

    修前文档教用户"删除 `http2 on;` 一行"，而 R-1 之后该行已不存在——
    用户会在文件里找不到、无从下手。
    """
    text = _doc()
    nginx_lines = [
        ln
        for ln in (_REPO / "deploy" / "nginx.conf").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    has_standalone_http2 = any(ln.strip().startswith("http2 ") for ln in nginx_lines)

    # 文档若仍指示处理 http2，其描述必须与 nginx.conf 现状一致
    if "http2" in text:
        assert not has_standalone_http2, "用例前提：nginx.conf 已不含独立 http2 指令行"
        assert (
            "删除 `http2 on;`" not in text and "删除 http2 on" not in text
        ), "D-2: 文档仍教用户删除 `http2 on;`，但该指令行已不存在——用户会找不到、无从下手"


def test_d3_sha256_entries_match_actual_files() -> None:
    """D-3: 文档列出的 SHA256 必须与实际文件一致（或该行已删除）。"""
    text = _doc()
    bad: list[str] = []
    for path_str, digest in re.findall(r"\|\s*(deploy/[\w./-]+)\s*\|\s*`([0-9a-f]{64})`", text):
        target = _REPO / path_str
        if not target.exists():
            bad.append(f"{path_str}（文件不存在，校验永远不过）")
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != digest:
            bad.append(f"{path_str}（文档 {digest[:12]}… ≠ 实际 {actual[:12]}…）")
    assert not bad, f"D-3: SHA256 与实装不符：{bad}"


def test_d4_env_table_covers_effective_vars() -> None:
    """D-4: env 表须含实际生效的关键变量，且队列深度默认值与代码一致。"""
    text = _doc()
    from backend.app.api.event_bus import EventBus

    assert "KYLIN_SSE_MAX_CONN" in text, "D-4: env 表缺 KYLIN_SSE_MAX_CONN（连接上限，三处在用）"

    m = re.search(r"KYLIN_SSE_QUEUE_MAX[^\n]*", text)
    assert m, "D-4: env 表缺 KYLIN_SSE_QUEUE_MAX"
    assert str(EventBus.DEFAULT_MAXSIZE) in m.group(
        0
    ), f"D-4: 文档里的 QUEUE_MAX 默认值与代码 {EventBus.DEFAULT_MAXSIZE} 不符：{m.group(0)}"


def test_d5_no_reference_to_deleted_unit() -> None:
    """D-5: 不得再以已删除的 deploy/kylin-safeops.service 为部署依据。"""
    text = _doc()
    weak_unit_lines = [
        ln
        for ln in text.splitlines()
        if "kylin-safeops.service" in ln and "kylin-safeops-agent.service" not in ln
    ]
    assert (
        not weak_unit_lines
    ), f"D-5: 仍引用已删除的弱版单元（{len(weak_unit_lines)} 处）：{weak_unit_lines[:3]}"
