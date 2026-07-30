"""P0-2 / P0-5 / P0-6: 部署脚本可用性守门。

P0-2 verify.sh 首检即死：`set -euo pipefail` + `((PASS++))`。后自增的算术展开
返回**自增前**的值，计数器为 0 时返回 0 → 退出码 1 → set -e 杀脚本。实测原脚本
只输出 4 行、汇总永不打印。另有第二处同类：`check "d" A | grep B` 会把 check 自身
的输出接进 grep（shell 先解析管道），grep 无匹配 → pipefail 再次杀脚本。

P0-5 nginx 主配置两条必做项此前零提及：limit_req_zone 缺失 → nginx -t 报 unknown
zone → nginx 拒启 → 前端与 API 全不可达。

P0-6 install.sh 要求在目标机 npm build，直接违反自家 LoongArch 铁律；且 nginx.conf
的 root 目录脚本既不建也不提。

  V-1 verify.sh 能跑完全部检查并打印汇总（不再首检即死）
  V-2 verify.sh 退出码 == 失败数（由检查结果决定，而非首条即死）
  V-3 verify.sh 不得再出现 ((VAR++)) 形式
  V-4 verify.sh 覆盖 sidecar（P0-1 的验证点，app 侧检查全绿也可能整站 502）
  V-5 前端可达性检查不得只打 80（301 会让 curl -sf 恒过，掩盖前端未部署）
  N-1 nginx 片段声明的 zone 名 ⇔ nginx.conf 里 limit_req 引用的 zone 名
  N-2 install.sh 输出提及主配置两条必做项
  F-1 install.sh 无可执行的 npm 调用（铁律：前端 x86 预构建）
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
_VERIFY_SH = _REPO / "deploy" / "verify.sh"
_INSTALL_SH = _REPO / "deploy" / "install.sh"
_NGINX_CONF = _REPO / "deploy" / "nginx.conf"
_HTTP_SNIPPET = _REPO / "deploy" / "nginx-http-snippet.conf"

_needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="需 bash 执行部署脚本")


def _code_lines(path: pathlib.Path) -> list[str]:
    return [
        ln
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


@_needs_bash
def test_v1_verify_sh_runs_to_completion() -> None:
    """V-1: 本机跑完整脚本，必须跑完所有检查并打印汇总行。

    本机没有这些服务，预期是"全 FAIL 但跑完"——这正好证明脚本不再首检即死。
    """
    result = subprocess.run(
        ["bash", str(_VERIFY_SH)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    out = result.stdout
    assert "=== 结果:" in out, f"V-1: 汇总行未打印（首检即死复发）；输出=\n{out}"

    checks = [ln for ln in out.splitlines() if "[PASS]" in ln or "[FAIL]" in ln]
    assert len(checks) >= 8, f"V-1: 仅执行 {len(checks)} 条检查，脚本中途退出"


@_needs_bash
def test_v2_exit_code_equals_failure_count() -> None:
    """V-2: 退出码由检查结果决定（== FAIL 数），而非首条即死的偶然值。"""
    result = subprocess.run(
        ["bash", str(_VERIFY_SH)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    m = re.search(r"=== 结果: (\d+) PASS, (\d+) FAIL ===", result.stdout)
    assert m, "V-2: 未能解析汇总行"
    fail_count = int(m.group(2))
    assert (
        result.returncode == fail_count
    ), f"V-2: 退出码 {result.returncode} != FAIL 数 {fail_count}"


def test_v3_no_postincrement_under_set_e() -> None:
    """V-3: 不得再用 ((VAR++))——set -e 下计数器为 0 时它会杀脚本。"""
    offenders = [ln for ln in _code_lines(_VERIFY_SH) if re.search(r"\(\(\w+\+\+\)\)", ln)]
    assert not offenders, f"V-3: 仍在使用 ((VAR++))：{offenders}"


def test_v4_verify_covers_sidecar() -> None:
    """V-4: 必须检查 sidecar——app 侧全绿时 sidecar 挂了仍是整站 502。"""
    text = _VERIFY_SH.read_text(encoding="utf-8")
    assert "kylin-proxy" in text, "V-4: 未检查 sidecar 服务状态"
    assert "8080" in text, "V-4: 未检查 sidecar 监听端口"


def test_v5_frontend_check_not_fooled_by_redirect() -> None:
    """V-5: 前端可达性不得只打 80——nginx 的 301 会让 curl -sf 恒过。"""
    checks = [ln for ln in _code_lines(_VERIFY_SH) if "前端首页" in ln]
    assert checks, "V-5: 未见前端可达性检查"
    joined = "\n".join(checks)
    assert (
        "https://" in joined or "443" in joined
    ), f"V-5: 前端检查仍只打 80，301 会让它恒过：{joined}"


def test_n1_snippet_zone_matches_nginx_conf() -> None:
    """N-1: 片段声明的 zone 名必须与 nginx.conf 里 limit_req 引用的一致。"""
    assert _HTTP_SNIPPET.exists(), "N-1: 缺 deploy/nginx-http-snippet.conf"
    snippet = _HTTP_SNIPPET.read_text(encoding="utf-8")
    declared = set(re.findall(r"limit_req_zone\s+\S+\s+zone=(\w+):", snippet))
    referenced = set(re.findall(r"limit_req\s+zone=(\w+)", _NGINX_CONF.read_text(encoding="utf-8")))
    assert referenced, "N-1: nginx.conf 未引用任何 zone（用例前提失效）"
    assert (
        referenced <= declared
    ), f"N-1: nginx.conf 引用 {referenced}，片段只声明 {declared}——nginx -t 会报 unknown zone"
    assert "server_names_hash_bucket_size" in snippet, "N-1: 片段缺 bucket size"


def test_n2_install_mentions_http_prereqs() -> None:
    """N-2: install.sh 输出须提及两条主配置必做项，否则运维不知道要加。"""
    text = _INSTALL_SH.read_text(encoding="utf-8")
    assert "limit_req_zone" in text, "N-2: install.sh 未提 limit_req_zone"
    assert "server_names_hash_bucket_size" in text, "N-2: install.sh 未提 bucket size"


def test_f1_install_has_no_npm_invocation() -> None:
    """F-1: install.sh 不得有可执行的 npm 调用（前端须在 x86 预构建）。"""
    offenders = [
        ln
        for ln in _code_lines(_INSTALL_SH)
        if re.search(r"(^|[^\w])npm\s+(ci|run|install)", ln) and "echo" not in ln
    ]
    assert not offenders, f"F-1: install.sh 仍在目标机跑 npm（违 LoongArch 铁律）：{offenders}"
