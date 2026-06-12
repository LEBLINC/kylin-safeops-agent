#!/usr/bin/env bash
# 场景3 清理 — 删除临时 I/O 测试文件

set -euo pipefail
DEMO_DIR="/tmp/demo-io"

dry_run=false
[[ "${1:-}" == "--dry-run" ]] && { dry_run=true; echo "[DRY-RUN] 以下为将要执行的步骤"; }
[[ "${1:-}" == "--help" ]] && { echo "用法: bash cleanup.sh [--dry-run|--help]"; echo "  删除 /tmp/demo-io 下的临时文件"; exit 0; }

echo "=== 场景3 [I/O 异常] 清理 ==="
if [[ -d "${DEMO_DIR}" ]]; then
  if $dry_run; then echo "  [DRY-RUN] rm -rf ${DEMO_DIR}"
  else rm -rf "${DEMO_DIR}"; echo "已删除 ${DEMO_DIR}"; fi
else echo "目录 ${DEMO_DIR} 不存在，跳过"; fi
