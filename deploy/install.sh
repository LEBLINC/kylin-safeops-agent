#!/usr/bin/env bash
# Kylin SafeOps Agent 部署脚本（麒麟 V11 + LoongArch）
# 安全红线：不执行 rm -rf / chmod 777 / curl|bash
# 涉及 root/sudo 的步骤标注 [需人工复核]

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="kylin-safeops"
INSTALL_DIR="/opt/kylin-safeops"
VENV_DIR="${INSTALL_DIR}/.venv"
PYTHON_BIN="python3.11"

dry_run=false
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true
  echo "[DRY-RUN] 以下为将要执行的步骤，不会实际修改系统"
elif [[ "${1:-}" == "--help" ]]; then
  echo "用法: bash install.sh [--dry-run|--help]"
  echo "  --dry-run  预览安装步骤，不实际执行"
  echo "  --help     显示此帮助"
  exit 0
fi

run() {
  if $dry_run; then
    echo "  [DRY-RUN] $*"
  else
    echo "  [EXEC] $*"
    "$@"
  fi
}

echo "=== Kylin SafeOps Agent 部署 ==="

# [需人工复核] 创建安装目录（如 /opt 需 root）
echo "[1/5] 创建安装目录"
run sudo mkdir -p "${INSTALL_DIR}"
run sudo chown "$(whoami):$(whoami)" "${INSTALL_DIR}"

# [需人工复核] 复制后端代码
echo "[2/5] 部署后端"
run cp -r "${PROJECT_DIR}/backend" "${INSTALL_DIR}/"
run cp -r "${PROJECT_DIR}/mcp_servers" "${INSTALL_DIR}/"
run cp "${PROJECT_DIR}/pyproject.toml" "${INSTALL_DIR}/"

# [需人工复核] 创建虚拟环境并安装依赖
echo "[3/5] 安装 Python 依赖"
if ! $dry_run; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  source "${VENV_DIR}/bin/activate"
  pip install --upgrade pip
  pip install -r "${INSTALL_DIR}/backend/requirements.txt" -c "${INSTALL_DIR}/backend/constraints.txt"
  deactivate
fi
$dry_run && echo "  [DRY-RUN] python3.11 -m venv ${VENV_DIR} && pip install -r ..."

# [需人工复核] 配置 systemd
echo "[4/5] 配置 systemd"
run sudo cp "${PROJECT_DIR}/deploy/kylin-safeops.service" /etc/systemd/system/

# ADR-0004：写 /etc/kylin-safeops/ldap.env 兜底——生产 KYLIN_LDAP_MOCK=false，
# 与 kylin-safeops.service 的硬编码 Environment= 形成双保险。运维若忘改 service
# 模板，至少 env 文件能拦下 mock 误启（lifespan fail-fast 见 app.py）。
echo "  [4.1/5] 写 /etc/kylin-safeops/ldap.env（KYLIN_LDAP_MOCK=false 兜底）"
if ! $dry_run; then
  run sudo mkdir -p /etc/kylin-safeops
  run sudo tee /etc/kylin-safeops/ldap.env >/dev/null <<'EOF'
# Kylin SafeOps LDAP mode — ADR-0004
# 生产必须 false；true 仅 demo/单测。
KYLIN_LDAP_MOCK=false
EOF
  run sudo chmod 0640 /etc/kylin-safeops/ldap.env
  run sudo chown root:kylin-safeops /etc/kylin-safeops/ldap.env 2>/dev/null || true
fi
$dry_run && echo "  [DRY-RUN] 写 /etc/kylin-safeops/ldap.env（KYLIN_LDAP_MOCK=false）"

run sudo systemctl daemon-reload
run sudo systemctl enable "${SERVICE_NAME}"

# 前端构建说明
echo "[5/5] 前端部署 (手动)"
echo "  前端为静态文件，构建后由 Nginx 直接服务。步骤："
echo "  1. cd ${PROJECT_DIR}/frontend && npm ci && npm run build"
echo "  2. 将 dist/ 目录复制到 Nginx 静态文件路径"
echo "  3. 配置 Nginx（参考 deploy/nginx.conf）"

echo "=== 部署完成 ==="
echo "启动服务: sudo systemctl start ${SERVICE_NAME}"
echo "查看状态: sudo systemctl status ${SERVICE_NAME}"
echo "查看日志: sudo journalctl -u ${SERVICE_NAME} -f"
