#!/usr/bin/env bash
# 场景2 清理 — 僵尸进程会在 30 秒后自动退出，无需手动清理
echo "=== 场景2 [僵尸进程] 清理 ==="
echo "僵尸父进程 30 秒后自动退出，无需手动清理"
echo "如需检查: ps aux | grep -E '[d]efunct|[s]leep 30'"
