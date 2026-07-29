#!/usr/bin/env bash
# Kylin SafeOps Agent 部署脚本（麒麟 V11 + LoongArch）
# 安全红线：不执行 rm -rf / chmod 777 / curl|bash
# 涉及 root/sudo 的步骤标注 [需人工复核]

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# 之七十五 R-3：app 单元收敛为 deploy/app/kylin-safeops-agent.service（完整版）。
SERVICE_NAME="kylin-safeops-agent"
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

# [需人工复核] 创建 kylin-safeops 系统用户（幂等：已存在则跳过）
# B1c（架构审计 154f767 §2）：app 单元 + proxy sidecar 单元均以此非 root 用户运行
# （最小权限；两个 systemd unit 的 User=kylin-safeops 与此一致）。
echo "[1/6] 创建 kylin-safeops 系统用户"
if ! $dry_run; then
  if id -u kylin-safeops >/dev/null 2>&1; then
    echo "  [SKIP] 用户 kylin-safeops 已存在"
  else
    run sudo useradd --system --no-create-home --shell /usr/sbin/nologin kylin-safeops
  fi
fi
$dry_run && echo "  [DRY-RUN] id -u kylin-safeops || useradd --system --no-create-home --shell /usr/sbin/nologin kylin-safeops"

# [需人工复核] 创建安装目录（如 /opt 需 root）
echo "[2/6] 创建安装目录"
run sudo mkdir -p "${INSTALL_DIR}"
run sudo chown "$(whoami):$(whoami)" "${INSTALL_DIR}"

# [需人工复核] 复制后端代码
echo "[3/6] 部署后端"
run cp -r "${PROJECT_DIR}/backend" "${INSTALL_DIR}/"
run cp -r "${PROJECT_DIR}/mcp_servers" "${INSTALL_DIR}/"
run cp -r "${PROJECT_DIR}/deploy/proxy" "${INSTALL_DIR}/deploy_proxy"
run cp -r "${PROJECT_DIR}/deploy/sso" "${INSTALL_DIR}/deploy_sso"
run cp "${PROJECT_DIR}/pyproject.toml" "${INSTALL_DIR}/"

# [需人工复核] 创建虚拟环境并安装依赖
echo "[4/6] 安装 Python 依赖"
if ! $dry_run; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  source "${VENV_DIR}/bin/activate"
  pip install --upgrade pip
  pip install -r "${INSTALL_DIR}/backend/requirements.txt" -c "${INSTALL_DIR}/backend/constraints.txt" \
    $([ -d "${PROJECT_DIR}/wheels" ] && echo "--find-links ${PROJECT_DIR}/wheels --no-index" || true)
  deactivate
fi
$dry_run && echo "  [DRY-RUN] python3.11 -m venv ${VENV_DIR} && pip install -r ..."

# [需人工复核] 配置 systemd —— B1c：双单元（app + proxy sidecar），缺 sidecar
# 单元时 nginx 只能直连 app（B1 前门洞）。
# 之七十五 R-3：app 单元收敛到 deploy/app/kylin-safeops-agent.service（完整版，
# 带 UMask=0077 / After=time-sync.target / EnvironmentFile / ReadWritePaths 覆盖
# 审计库目录）；弱版 deploy/kylin-safeops.service 已删，不再存在双份漂移。
echo "[5/6] 配置 systemd（app 单元 + proxy sidecar 单元）"
run sudo cp "${PROJECT_DIR}/deploy/app/kylin-safeops-agent.service" /etc/systemd/system/
run sudo cp "${PROJECT_DIR}/deploy/proxy/kylin-proxy.service" /etc/systemd/system/

# ADR-0004：写 /etc/kylin-safeops/agent.env 兜底——生产 KYLIN_LDAP_MOCK=false，
# 与 kylin-safeops-agent.service 的 Environment= 硬编码形成双保险。运维若忘改
# service 模板，至少 env 文件能拦下 mock 误启（lifespan fail-fast 见 app.py）。
# 文件名与单元的 EnvironmentFile= 必须一致——之七十五 R-3 前二者分别写
# ldap.env / agent.env，单元会因 EnvironmentFile 缺失而启动失败。
echo "  [5.1/6] 写 /etc/kylin-safeops/agent.env（KYLIN_LDAP_MOCK=false 兜底）"
if ! $dry_run; then
  run sudo mkdir -p /etc/kylin-safeops
  if [[ -f /etc/kylin-safeops/agent.env ]]; then
    echo "  [SKIP] /etc/kylin-safeops/agent.env 已存在，不覆盖（防误清运维已填密钥）"
  else
    run sudo tee /etc/kylin-safeops/agent.env >/dev/null <<'EOF'
# /etc/kylin-safeops/agent.env — app 侧环境变量（完整示例见 deploy/app/agent.env.example）
# ADR-0004：生产必须 false；true 仅 demo/单测。
KYLIN_LDAP_MOCK=false
# 生产必须 proxy；dev 模式角色可伪造，严禁生产。
KYLIN_AUTH_MODE=proxy
# 反代签名共享密钥——占位值，运维必须替换为 openssl rand -hex 32 的真值。
KYLIN_PROXY_AUTH_SECRET=CHANGE_ME_32BYTE_HEX
# 审计库（单元 ReadWritePaths 已覆盖该目录）
KYLIN_AUDIT_DB=/var/lib/kylin-safeops/audit.db
EOF
    run sudo chmod 0600 /etc/kylin-safeops/agent.env
    run sudo chown root:kylin-safeops /etc/kylin-safeops/agent.env 2>/dev/null || true
  fi
fi
$dry_run && echo "  [DRY-RUN] 写 /etc/kylin-safeops/agent.env（KYLIN_LDAP_MOCK=false）"

# 审计库目录：单元 ProtectSystem=strict + ReadWritePaths=/var/lib/kylin-safeops，
# 目录不存在则 systemd 直接拒绝启动。0700 归 kylin-safeops（属主漂移是 VM 上
# "readonly database" 部署阻塞的根因，见 deploy/audit/README.md）。
echo "  [5.1b/6] 创建审计库目录 /var/lib/kylin-safeops（0700 kylin-safeops）"
run sudo install -d -m 0700 -o kylin-safeops -g kylin-safeops /var/lib/kylin-safeops

# B1c：proxy sidecar 密钥/LDAP 凭据带外注入骨架——kylin-proxy.service 用
# EnvironmentFile=/etc/kylin/proxy.env（不硬编码进 unit）。此处只建 0600 骨架
# （占位值），真实密钥由运维手工填入，绝不由本脚本生成或写入版本库。
echo "  [5.2/6] 写 /etc/kylin/proxy.env 骨架（0600，占位值待运维填写）"
if ! $dry_run; then
  run sudo mkdir -p /etc/kylin
  if [[ -f /etc/kylin/proxy.env ]]; then
    echo "  [SKIP] /etc/kylin/proxy.env 已存在，不覆盖（防误清运维已填真值）"
  else
    run sudo tee /etc/kylin/proxy.env >/dev/null <<'EOF'
# Kylin SafeOps proxy sidecar 配置骨架 —— 运维填真值后 chmod 0600。
# 反代签名密钥（32 字节 hex；生成：openssl rand -hex 32）
KYLIN_PROXY_AUTH_SECRET=CHANGE_ME_32BYTE_HEX
# 真 LDAP（决策⑨硬阻断：禁止 true）
KYLIN_LDAP_MOCK=false
KYLIN_LDAP_URL=ldap://CHANGE_ME:389
KYLIN_LDAP_BIND_DN=CHANGE_ME
KYLIN_LDAP_BIND_PASSWORD=CHANGE_ME
KYLIN_LDAP_BASE_DN=CHANGE_ME
KYLIN_LDAP_USER_FILTER=(uid={0})
KYLIN_LDAP_GROUP_ATTR=memberOf
KYLIN_UPSTREAM=http://127.0.0.1:8000
EOF
    run sudo chmod 0600 /etc/kylin/proxy.env
    run sudo chown root:kylin-safeops /etc/kylin/proxy.env 2>/dev/null || true
  fi
fi
$dry_run && echo "  [DRY-RUN] 写 /etc/kylin/proxy.env 骨架（0600）"

run sudo systemctl daemon-reload
run sudo systemctl enable "${SERVICE_NAME}"
run sudo systemctl enable kylin-proxy

# 前端构建说明
echo "[6/6] 前端部署 (手动)"
echo "  前端为静态文件，构建后由 Nginx 直接服务。步骤："
echo "  1. cd ${PROJECT_DIR}/frontend && npm ci && npm run build"
echo "  2. 将 dist/ 目录复制到 Nginx 静态文件路径"
echo "  3. 配置 Nginx（参考 deploy/nginx.conf，443/TLS → proxy sidecar:8080 → app:8000）"
echo "  4. 编辑 /etc/kylin/proxy.env 填真实密钥/LDAP 配置（占位值不可用于生产）"
echo "  5. 编辑 /etc/kylin-safeops/agent.env 填 KYLIN_PROXY_AUTH_SECRET 真值"
echo "     （须与 /etc/kylin/proxy.env 的同名密钥完全一致，否则签名校验必失败）"

echo "=== 部署完成 ==="
echo "启动服务: sudo systemctl start ${SERVICE_NAME} kylin-proxy"
echo "查看状态: sudo systemctl status ${SERVICE_NAME} kylin-proxy"
echo "查看日志: sudo journalctl -u ${SERVICE_NAME} -u kylin-proxy -f"
