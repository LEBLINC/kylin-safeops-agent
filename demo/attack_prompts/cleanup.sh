#!/usr/bin/env bash
# Demo: prompt injection attack - cleanup
set -euo pipefail

DEMO_LOG="/var/log/attack-demo.log"

dry_run=false
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true; echo "[DRY-RUN] Steps to be executed:"
elif [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash cleanup.sh [--dry-run|--help]"
  echo "  Removes ${DEMO_LOG}"; exit 0
fi

echo "=== Demo: Prompt Injection Attack - Cleanup ==="
if [[ -f "${DEMO_LOG}" ]]; then
  if $dry_run; then
    echo "  [DRY-RUN] rm ${DEMO_LOG}"
  else
    rm "${DEMO_LOG}"
    echo "Removed ${DEMO_LOG}"
  fi
else
  echo "File ${DEMO_LOG} does not exist, skipping"
fi
