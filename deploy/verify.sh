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
# 之七十五 H-5：原来查 /health——全仓无此路由，必 404，这条 check 永远 FAIL。
# 改查 /api/system/ready（readiness 探针：审计库可写 + bus 存活 + 活跃连接未超阈值）。
# 刻意不用 /api/llm/health：那个端点会额外触发真 LLM 端点连通性探测，
# 部署冒烟阶段不应依赖外部网关可达。
#
# 认证：/api/system/ready 无鉴权依赖，dev / proxy 两种模式都能直连 127.0.0.1:8000。
# 其余 /api/* 端点在 proxy 模式下要求反代注入签名身份——若要在本机 curl 它们，
# 需经反代（nginx→sidecar:8080）或用 backend/app/api/sign_cli.py 自带签名头。
check "API readiness 就绪" curl -sf http://127.0.0.1:8000/api/system/ready

echo ""
echo "--- 前端服务 ---"
check "Nginx 运行中" systemctl is-active --quiet nginx
check "前端首页可达" curl -sf http://127.0.0.1/

echo ""
echo "=== 结果: ${PASS} PASS, ${FAIL} FAIL ==="
exit $FAIL
