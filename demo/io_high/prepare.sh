#!/usr/bin/env bash
# 场景3 准备 — 模拟高 I/O 负载
# 安全：dd 写入 10 秒后自动停止，仅操作 /tmp/demo-io 临时目录

set -euo pipefail

DEMO_DIR="/tmp/demo-io"
IO_DURATION_SEC=10

dry_run=false
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true; echo "[DRY-RUN] 以下为将要执行的步骤"
elif [[ "${1:-}" == "--help" ]]; then
  echo "用法: bash prepare.sh [--dry-run|--help]"
  echo "  在 /tmp/demo-io 产生 ${IO_DURATION_SEC} 秒高 I/O 负载"; exit 0
fi

echo "=== 场景3 [I/O 异常] 环境准备 ==="
if $dry_run; then
  echo "  [DRY-RUN] 在 ${DEMO_DIR} 产生 ${IO_DURATION_SEC}s I/O 负载"
else
  run() { mkdir -p "${DEMO_DIR}"; timeout ${IO_DURATION_SEC} dd if=/dev/zero of="${DEMO_DIR}/io_test.dat" bs=1M status=progress 2>/dev/null || true; }
  run &
  IO_PID=$!
  echo "I/O 负载已启动 (PID: ${IO_PID}, 持续 ${IO_DURATION_SEC}s)"
  echo "准备完成。现在在 ChatView 中输入："磁盘 I/O 异常，帮我排查""
fi
