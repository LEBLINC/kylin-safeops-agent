#!/usr/bin/env bash
# 场景1 准备 — 模拟磁盘满
# 安全：仅在 /tmp/demo-disk 下创建文件，不修改系统分区

set -euo pipefail

DEMO_DIR="/tmp/demo-disk"
FILE_SIZE_MB=500

dry_run=false
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true; echo "[DRY-RUN] 以下为将要执行的步骤"
elif [[ "${1:-}" == "--help" ]]; then
  echo "用法: bash prepare.sh [--dry-run|--help]"
  echo "  在 /tmp/demo-disk 创建大文件模拟磁盘满"
  echo "  --dry-run  预览操作"; echo "  --help     显示此帮助"
  exit 0
fi

run() { if $dry_run; then echo "  [DRY-RUN] $*"; else echo "  [EXEC] $*"; "$@"; fi }

echo "=== 场景1 [磁盘满] 环境准备 ==="
run mkdir -p "${DEMO_DIR}"
run dd if=/dev/zero of="${DEMO_DIR}/large_file.dat" bs=1M count=${FILE_SIZE_MB} status=progress 2>/dev/null || true
echo "已创建 ${DEMO_DIR}/large_file.dat (${FILE_SIZE_MB}MB)"
echo "准备完成。现在在 ChatView 中输入："磁盘满了，帮我查原因""
