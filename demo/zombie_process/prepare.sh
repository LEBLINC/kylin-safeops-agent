#!/usr/bin/env bash
# 场景2 准备 — 模拟僵尸进程
# 安全：创建的子进程 5 秒后自动退出，父进程 30 秒后退出，不会永久残留

set -euo pipefail

dry_run=false
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true; echo "[DRY-RUN] 以下为将要执行的步骤"
elif [[ "${1:-}" == "--help" ]]; then
  echo "用法: bash prepare.sh [--dry-run|--help]"
  echo "  创建短期子进程模拟僵尸状态"; exit 0
fi

echo "=== 场景2 [僵尸进程] 环境准备 ==="
if $dry_run; then
  echo "  [DRY-RUN] bash -c 'sleep 5 & exec sleep 30'   (子进程变为 defunct 约 25 秒)"
else
  # 父进程 sleep 30s，子进程 sleep 5s → 子进程在 5s-30s 间为 defunct
  bash -c 'sleep 5 & exec sleep 30' &
  ZOMBIE_PARENT=$!
  echo "僵尸模拟已启动 (PID: ${ZOMBIE_PARENT})"
  echo "子进程将在 5 秒后退出变为 defunct，父进程 30 秒后退出"
  echo "准备完成。现在在 ChatView 中输入："发现僵尸进程，帮我诊断""
fi
