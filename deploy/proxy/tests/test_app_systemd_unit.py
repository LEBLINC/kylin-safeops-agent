"""之七十五 R-3: app systemd 单元收敛守门（静态解析，不依赖 bash/root）。

收敛前 deploy/ 同时存在两份 app 单元：
  - deploy/kylin-safeops.service（弱版，install.sh:77 实际安装的那份）
  - deploy/app/kylin-safeops-agent.service（完整版，UMask=0077 / EnvironmentFile /
    ReadWritePaths 覆盖审计库目录，但从未被任何脚本引用）
即"装的不是硬的那份"。R-3 删弱版、install.sh 改装完整版，本用例锁死该收敛：

  R3-1 install.sh 引用的 app 单元文件真实存在（防再次指向不存在/已删的路径）
  R3-2 弱版单元已删除（防回退到双份漂移）
  R3-3 完整版单元含 UMask=0077 / EnvironmentFile= / ReadWritePaths 覆盖
       /var/lib/kylin-safeops
  R3-4 单元的 EnvironmentFile= 路径与 install.sh 实际创建的 env 文件一致
       （收敛前分别是 agent.env / ldap.env，单元会因 EnvironmentFile 缺失起不来）
  R3-5 install.sh 创建了 ReadWritePaths 指向的审计库目录
       （ProtectSystem=strict 下目录不存在 systemd 直接拒启）
"""

from __future__ import annotations

import pathlib
import re

_DEPLOY = pathlib.Path(__file__).resolve().parents[2]
_INSTALL_SH = _DEPLOY / "install.sh"
_APP_UNIT = _DEPLOY / "app" / "kylin-safeops-agent.service"


def _install_sh_text() -> str:
    assert _INSTALL_SH.exists(), f"install.sh 不存在于 {_INSTALL_SH}"
    return _INSTALL_SH.read_text(encoding="utf-8")


def _app_unit_text() -> str:
    assert _APP_UNIT.exists(), f"app 单元不存在于 {_APP_UNIT}"
    return _APP_UNIT.read_text(encoding="utf-8")


def _unit_directive(text: str, key: str) -> list[str]:
    """取某指令的全部取值（忽略注释行）。"""
    values = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        if name.strip() == key:
            values.append(value.strip())
    return values


def test_r3_1_install_sh_references_existing_app_unit() -> None:
    """R3-1: install.sh 拷贝的 app 单元路径必须真实存在。"""
    text = _install_sh_text()
    refs = re.findall(r"\$\{PROJECT_DIR\}/(deploy/\S*?\.service)", text)
    assert refs, "R3-1: install.sh 未引用任何 .service 单元文件"
    repo_root = _DEPLOY.parent
    for rel in refs:
        assert (repo_root / rel).exists(), f"R3-1: install.sh 引用的单元不存在：{rel}"
    assert any(
        r.endswith("app/kylin-safeops-agent.service") for r in refs
    ), f"R3-1: 必须安装完整版 app 单元，实际引用 {refs}"


def test_r3_2_weak_unit_removed() -> None:
    """R3-2: 弱版 deploy/kylin-safeops.service 已删（防双份漂移回退）。"""
    weak = _DEPLOY / "kylin-safeops.service"
    assert not weak.exists(), "R3-2: 弱版 app 单元应已删除，不得与完整版并存"


def test_r3_3_app_unit_hardening_directives() -> None:
    """R3-3: 完整版单元含 UMask=0077 / EnvironmentFile= / 审计库 ReadWritePaths。"""
    text = _app_unit_text()
    assert _unit_directive(text, "UMask") == ["0077"], "R3-3: 缺 UMask=0077（审计库权限双保险）"
    assert _unit_directive(text, "EnvironmentFile"), "R3-3: 缺 EnvironmentFile=（密钥带外注入）"
    rw_paths = " ".join(_unit_directive(text, "ReadWritePaths"))
    assert (
        "/var/lib/kylin-safeops" in rw_paths
    ), f"R3-3: ReadWritePaths 未覆盖审计库目录，实际 {rw_paths!r}"


def test_r3_4_environment_file_path_matches_install_sh() -> None:
    """R3-4: 单元 EnvironmentFile= 路径必须由 install.sh 真正创建。"""
    env_files = _unit_directive(_app_unit_text(), "EnvironmentFile")
    assert env_files, "R3-4: 单元未声明 EnvironmentFile="
    install_text = _install_sh_text()
    for env_file in env_files:
        path = env_file.lstrip("-")  # systemd 前缀 `-` 表示文件缺失时不报错
        assert path in install_text, f"R3-4: install.sh 未创建单元所需的 {path}（单元将启动失败）"


def test_r3_5_install_sh_creates_audit_db_dir() -> None:
    """R3-5: ProtectSystem=strict 下审计库目录必须由 install.sh 预建。"""
    install_text = _install_sh_text()
    assert (
        "/var/lib/kylin-safeops" in install_text
    ), "R3-5: install.sh 未创建 /var/lib/kylin-safeops（strict 下 systemd 拒启）"


def test_h5_verify_sh_probes_existing_route() -> None:
    """之七十五 H-5: verify.sh 的健康检查必须指向真实存在的路由。

    收敛前查的是 /health——全仓无此路由（实测 create_app() 的 routes 里没有），
    这条 check 在任何环境都必然 FAIL，等于部署验证脚本自带一条永假断言：
    要么运维习惯性忽略它（那整个脚本的可信度就没了），要么每次部署都被它误导。

    也不该改用 /api/llm/health：那个端点会额外触发真 LLM 端点连通性探测，
    部署冒烟阶段不应依赖外部网关可达。
    """
    verify_sh = _DEPLOY / "verify.sh"
    assert verify_sh.exists(), f"verify.sh 不存在于 {verify_sh}"
    text = verify_sh.read_text(encoding="utf-8")

    assert "/api/system/ready" in text, "H-5: 应改查 /api/system/ready readiness 探针"
    # 排除注释行后不得再出现对 /health 的探测
    probe_lines = [
        ln
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#") and "curl" in ln
    ]
    for line in probe_lines:
        assert ":8000/health" not in line, f"H-5: 仍在探测不存在的 /health：{line.strip()}"
    assert not any(
        "/api/llm/health" in ln for ln in probe_lines
    ), "H-5: 不应用 /api/llm/health 做部署冒烟（会触发外部 LLM 连通性探测）"
