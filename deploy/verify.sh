#!/usr/bin/env bash
# Kylin SafeOps Agent 部署后验证命令
# 用法: bash deploy/verify.sh
# 安全：全部为只读状态查询，不执行任何修改操作

set -euo pipefail

PASS=0
FAIL=0

check() {
  local desc="$1"; shift
  if "$@" > /dev/null 2>&1; then
    echo "  [PASS] $desc"
    ((PASS++))
  else
    echo "  [FAIL] $desc"
    ((FAIL++))
  fi
}

echo "=== Kylin SafeOps Agent 部署验证 ==="
echo ""

echo "--- 系统环境 ---"
check "Python 3.11 可用" python3.11 --version
check "systemctl 可用" which systemctl
check "Nginx 可用" which nginx

echo ""
echo "--- 后端服务 ---"
check "systemd service 存在" systemctl list-unit-files | grep -q kylin-safeops
check "端口 8000 监听" ss -tlnp | grep -q ':8000'
check "API 健康检查" curl -sf http://127.0.0.1:8000/health

echo ""
echo "--- 前端服务 ---"
check "Nginx 运行中" systemctl is-active --quiet nginx
check "前端首页可达" curl -sf http://127.0.0.1/

echo ""
echo "=== 结果: ${PASS} PASS, ${FAIL} FAIL ==="
exit $FAIL
