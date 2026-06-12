#!/usr/bin/env bash
# 场景1 清理 — 删除模拟数据

set -euo pipefail

DEMO_DIR="/tmp/demo-disk"

dry_run=false
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true; echo "[DRY-RUN] 以下为将要执行的步骤"
elif [[ "${1:-}" == "--help" ]]; then
  echo "用法: bash cleanup.sh [--dry-run|--help]"
  echo "  删除 /tmp/demo-disk 下的模拟文件"; exit 0
fi

echo "=== 场景1 [磁盘满] 清理 ==="
if [[ -d "${DEMO_DIR}" ]]; then
  if $dry_run; then
    echo "  [DRY-RUN] rm -rf ${DEMO_DIR}"
  else
    rm -rf "${DEMO_DIR}"
    echo "已删除 ${DEMO_DIR}"
  fi
else
  echo "目录 ${DEMO_DIR} 不存在，跳过"
fi
