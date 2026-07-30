"""P0-1: 部署目录布局 / unit 模块路径 / 源码 import 三者一致性守门。

修前的断裂：install.sh 把 `deploy/proxy` 拷成 `${INSTALL_DIR}/deploy_proxy`（下划线），
而 sidecar 单元是 `ExecStart=... uvicorn deploy.proxy.proxy:app`（点分），
`proxy.py` 内部又 `from deploy.proxy._sign import ...` / `from deploy.sso.ldap_client
import ...`。目录名与模块路径不匹配 → sidecar 启动即
`ModuleNotFoundError: No module named 'deploy'` → 永不启动。
后果不是"某功能不可用"而是**产品对外完全不可用**：app 只绑 127.0.0.1 无旁路，
nginx 443→8080 全 502。

本用例从**同一来源解析三者**再交叉比对，任一漂移即红：
  L-1 install.sh 拷贝出的目录名 ⇔ unit ExecStart 的模块路径
  L-2 unit ExecStart 的模块路径 ⇔ proxy.py 内部 import 的顶层包
  L-3 install.sh 不得再出现 deploy_proxy / deploy_sso 下划线目录名
  L-4 真按 install.sh 的布局建目录后，unit 的模块路径确实可解析（行为断言）
  L-5 前端静态根目录：install.sh 建的路径 ⇔ nginx.conf 的 root
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
_INSTALL_SH = _REPO / "deploy" / "install.sh"
_PROXY_UNIT = _REPO / "deploy" / "proxy" / "kylin-proxy.service"
_PROXY_PY = _REPO / "deploy" / "proxy" / "proxy.py"
_NGINX_CONF = _REPO / "deploy" / "nginx.conf"


def _install_sh() -> str:
    return _INSTALL_SH.read_text(encoding="utf-8")


def _exec_start_module() -> str:
    """从 unit 的 ExecStart 里取 uvicorn 的模块路径，如 deploy.proxy.proxy:app。"""
    text = _PROXY_UNIT.read_text(encoding="utf-8")
    m = re.search(r"ExecStart=.*uvicorn\s+([\w.]+):(\w+)", text)
    assert m, "未能从 unit 解析出 uvicorn 模块路径"
    return m.group(1)


def _copied_dirs() -> list[str]:
    """从 install.sh 解析 deploy/ 下各子包被拷到的目标目录（相对 INSTALL_DIR）。"""
    text = _install_sh()
    dests = []
    for m in re.finditer(
        r'cp -r "\$\{PROJECT_DIR\}/deploy/(\w+)" "\$\{INSTALL_DIR\}/([\w/]*)"', text
    ):
        src_pkg, dest = m.group(1), m.group(2).rstrip("/")
        dests.append(f"{dest}/{src_pkg}" if dest else src_pkg)
    assert dests, "未能从 install.sh 解析出 deploy 子包的拷贝目标"
    return dests


def test_l1_install_dest_matches_unit_module_path() -> None:
    """L-1: install.sh 拷出的目录名必须能承载 unit 声明的模块路径。"""
    module_path = _exec_start_module()  # deploy.proxy.proxy
    expected_dir = "/".join(module_path.split(".")[:-1])  # deploy/proxy
    assert expected_dir in _copied_dirs(), (
        f"L-1: unit 要 {expected_dir}/，install.sh 实际拷到 {_copied_dirs()}"
        "——目录名与模块路径不匹配，sidecar 启动即 ModuleNotFoundError"
    )


def test_l2_unit_module_matches_source_imports() -> None:
    """L-2: proxy.py 内部 import 的顶层包必须与 unit 模块路径同根，且都被拷贝。"""
    src = _PROXY_PY.read_text(encoding="utf-8")
    imported = {m.group(1) for m in re.finditer(r"^from ([\w.]+) import ", src, flags=re.MULTILINE)}
    deploy_imports = {i for i in imported if i.startswith("deploy.")}
    assert deploy_imports, "proxy.py 未见 deploy.* import（用例前提失效，需复核）"

    copied = set(_copied_dirs())
    for mod in deploy_imports:
        pkg_dir = "/".join(mod.split(".")[:2])  # deploy.sso.ldap_client → deploy/sso
        assert pkg_dir in copied, (
            f"L-2: proxy.py 导入 {mod}，但 install.sh 未把 {pkg_dir}/ 拷到位"
            "（修前正是漏了 deploy_sso→deploy/sso，文档补救也只软链了 proxy）"
        )


def test_l3_no_underscore_dirs_in_install() -> None:
    """L-3: install.sh 不得再出现 deploy_proxy / deploy_sso 下划线目录名。"""
    code_lines = [
        ln for ln in _install_sh().splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]
    offenders = [ln for ln in code_lines if "deploy_proxy" in ln or "deploy_sso" in ln]
    assert not offenders, f"L-3: 仍在使用下划线目录名：{offenders}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="需 bash 复刻 install.sh 布局")
def test_l4_layout_actually_importable(tmp_path: pathlib.Path) -> None:
    """L-4: 按 install.sh 的布局建目录后，unit 的模块路径确实可解析（行为断言）。

    这是与 L-1/L-2 的静态比对互补的一条——即便三处字符串都改对了，若
    PEP 420 命名空间包在该布局下不成立，sidecar 依然起不来。
    """
    install_root = tmp_path / "opt"
    for rel in _copied_dirs():
        dest = install_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(_REPO / "deploy" / rel.split("/")[-1], dest)

    module_path = _exec_start_module()
    probe = (
        f"import importlib.util, sys; sys.path.insert(0, r'{install_root}');"
        f"spec = importlib.util.find_spec('{module_path}');"
        "print('OK' if spec else 'MISSING')"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60
    )
    assert "OK" in result.stdout, (
        f"L-4: 按部署布局无法解析 {module_path}；stdout={result.stdout!r} "
        f"stderr={result.stderr[-300:]!r}"
    )


def test_l5_web_root_matches_nginx_root() -> None:
    """L-5: install.sh 部署前端的目录 ⇔ nginx.conf 的 root（此前脚本根本不建该目录）。"""
    m = re.search(r'^WEB_ROOT="([^"]+)"', _install_sh(), flags=re.MULTILINE)
    assert m, "L-5: install.sh 未定义 WEB_ROOT"
    web_root = m.group(1)

    nginx = _NGINX_CONF.read_text(encoding="utf-8")
    roots = re.findall(r"^\s*root\s+([^;]+);", nginx, flags=re.MULTILINE)
    assert web_root in [
        r.strip() for r in roots
    ], f"L-5: install.sh 部署到 {web_root}，nginx.conf root 为 {roots}——不一致即 404"
