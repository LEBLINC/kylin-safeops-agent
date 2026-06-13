#!/bin/bash
# Kylin SafeOps Agent — 沙箱 wrapper 脚本（PR2b）
#
# 用途：Agent 进程可调用此 wrapper 代替直接调用命令。
#       wrapper 负责：systemd-run --scope → 真命令（外层 sudo 由 sudoers/调用方决定）。
#       参数由 Python executor 传入，本脚本不做任何解析/校验/拼接。
#
# 部署：
#   cp deploy/sandbox/kylin-safeops-run.sh /usr/local/bin/kylin-safeops-run
#   chmod 0755 /usr/local/bin/kylin-safeops-run
#
# 调用方式：kylin-safeops-run <profile> <timeout> <cmd> [args...]
#   profile: readonly | limited_write
#   timeout: 秒数（作为 systemd 单元 backstop，主超时由 executor 控制）
#   cmd args...: 被包裹的真实命令及参数
#
# 安全铁律：
# - 本脚本不解析命令内容、不做路径规一化——全部由 Python 层完成。
# - 本脚本只做 systemd-run 参数组装 + exec，不引入新的攻击面。
# - 不接受 stdin / 不读 env（除 PATH）/ 不写临时文件。

set -euo pipefail

PROFILE="${1:?usage: $0 <profile> <timeout> <cmd> [args...]}"
TIMEOUT="${2:?usage: $0 <profile> <timeout> <cmd> [args...]}"
shift 2

if [ $# -eq 0 ]; then
    echo "error: no command specified" >&2
    exit 127
fi

# 基线安全属性（全 profile 共有）
BASE_PROPS=(
    -p ProtectHome=yes
    -p PrivateTmp=yes
    -p NoNewPrivileges=yes
    -p ProtectKernelTunables=yes
    -p ProtectKernelModules=yes
    -p ProtectControlGroups=yes
)

# profile 专属属性
case "$PROFILE" in
    readonly)
        EXTRA_PROPS=(
            -p ProtectSystem=strict
            -p ReadOnlyPaths=/
        )
        ;;
    limited_write)
        EXTRA_PROPS=()
        ;;
    *)
        echo "error: unknown profile '$PROFILE'" >&2
        exit 1
        ;;
esac

exec /usr/bin/systemd-run \
    --scope \
    --quiet \
    -p "RuntimeMaxSec=${TIMEOUT}" \
    "${BASE_PROPS[@]}" \
    "${EXTRA_PROPS[@]}" \
    -- \
    "$@"
