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
    # 必须用 PASS=$((PASS+1)) 而非 ((PASS++))：后自增的算术展开返回的是**自增前**的值，
    # 计数器为 0 时返回 0 → 算术展开退出码 1 → 与第 6 行的 set -e 叠加直接杀掉脚本。
    # 现象是"跑到第一条检查就静默退出、汇总行永不打印"，而退出码看起来还像正常。
    PASS=$((PASS+1))
  else
    echo "  [FAIL] $desc"
    FAIL=$((FAIL+1))
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
# 注意：带管道的检查必须整体包进 bash -c，否则 `check "desc" A | grep B` 会把
# **check 自身的输出**接进 grep（shell 先解析管道再解析命令），grep 无匹配即
# 非 0，叠加 pipefail 直接杀脚本——现象同样是"跑一半静默退出"。
check "systemd service 存在" bash -c 'systemctl list-unit-files | grep -q kylin-safeops'
check "端口 8000 监听" bash -c 'ss -tlnp | grep -q ":8000"'
# 之七十五 H-5：原来查 /health——全仓无此路由，必 404，这条 check 永远 FAIL。
# 改查 /api/system/ready（readiness 探针：审计库可写 + bus 存活 + 活跃连接未超阈值）。
# 刻意不用 /api/llm/health：那个端点会额外触发真 LLM 端点连通性探测，
# 部署冒烟阶段不应依赖外部网关可达。
#
# 认证：/api/system/ready 无鉴权依赖，dev / proxy 两种模式都能直连 127.0.0.1:8000。
# 其余 /api/* 端点在 proxy 模式下要求反代注入签名身份——若要在本机 curl 它们，
# 需经反代（nginx→sidecar:8080）或用 backend/app/api/sign_cli.py 自带签名头。
check "API readiness 就绪" curl -sf http://127.0.0.1:8000/api/system/ready
# sidecar 是前门的必经一跳：app 只绑 127.0.0.1，sidecar 起不来则 nginx 443→8080
# 全 502、产品对外完全不可用，而上面两条 app 侧检查仍会 PASS——必须单独验。
check "反代 sidecar 运行中" systemctl is-active --quiet kylin-proxy
check "sidecar 端口 8080 监听" bash -c 'ss -tlnp | grep -q ":8080"'

echo ""
echo "--- 前端服务 ---"
check "Nginx 运行中" systemctl is-active --quiet nginx
# 打 80 端口只会拿到 301（nginx.conf 的 http→https 强制跳转），curl -sf 对 3xx
# 返回 0 → 这条检查恒过，前端根本没部署也看不出来。改打 443 并要求 2xx：
# --fail-with-body 对 4xx/5xx 返非 0，-o /dev/null -w 取实际码再比对。
check "前端首页可达（443 返 2xx）" bash -c '
  code=$(curl -sk -o /dev/null -w "%{http_code}" https://127.0.0.1/ || echo 000)
  [ "${code#2}" != "$code" ]'

echo ""
echo "=== 结果: ${PASS} PASS, ${FAIL} FAIL ==="
exit $FAIL
