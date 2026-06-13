#!/usr/bin/env bash
# kylin-safeops-run.sh — Kylin SafeOps Agent 沙箱唯一执行入口（PR2b-v2）
#
# 用法: kylin-safeops-run.sh <readonly|limited_write|none> -- <cmd> [args...]
# 由 PrivilegeExecutor 通过 sudo 调用。
#
# 机制：systemd-run 瞬态 service（--pipe --wait --collect --quiet，非 --scope）。
#   scope 只做 cgroup 登记、不经 fork/exec，mount-namespace 类保护属性
#   （ProtectSystem/ReadOnlyPaths/PrivateTmp/...）在 scope 下被静默忽略；
#   瞬态 service 由 systemd 真 fork/exec，保护属性才真正落地。
#
# 安全属性在此硬编码（单一事实来源），Python 侧只传 profile + inner argv。
# 即使 Agent 进程被攻陷，也无法通过 -p 注入削弱沙箱（配合 sudoers 仅放行本脚本，O12 闭合）。
#
# 安全属性说明：
#   NoNewPrivileges=yes      禁止 setuid/capabilities 提权
#   ProtectKernelTunables    禁改 /proc/sys、/sys 等内核可调项
#   ProtectKernelModules     禁加载/卸载内核模块
#   ProtectControlGroups     /sys/fs/cgroup 只读
#   ProtectHome=yes          /home /root /run/user 不可见
#   PrivateTmp=yes           独立 /tmp /var/tmp
#   ProtectSystem=strict     整个文件系统层级只读（readonly profile 专属）
#   ReadOnlyPaths=/          冗余加固：根只读（readonly profile 专属）
#
# --pipe：stdin/stdout/stderr 接回调用者 → create_subprocess_exec(stdout=PIPE) 可捕获
# --wait：阻塞并透传退出码 → 方案 B 语义不破
# --collect：失败时回收瞬态单元
# --quiet：抑制 systemd-run 自身输出
set -euo pipefail

PROFILE="${1:?用法: $0 <readonly|limited_write|none> -- <cmd> [args...]}"
shift
[[ "${1:-}" == "--" ]] && shift
[[ $# -eq 0 ]] && { echo "缺少命令" >&2; exit 1; }

SYSTEMD_RUN=/usr/bin/systemd-run
COMMON_PROPS=(
    -p NoNewPrivileges=yes
    -p ProtectKernelTunables=yes
    -p ProtectKernelModules=yes
    -p ProtectControlGroups=yes
    -p ProtectHome=yes
    -p PrivateTmp=yes
)
# 确保 inner command 获得安全 PATH / locale
ENV_PROPS=(
    -p "Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    -p "Environment=LANG=C.UTF-8"
    -p "Environment=LC_ALL=C.UTF-8"
)

case "$PROFILE" in
    readonly)
        exec "$SYSTEMD_RUN" --pipe --wait --collect --quiet \
            "${COMMON_PROPS[@]}" \
            -p ProtectSystem=strict \
            -p ReadOnlyPaths=/ \
            "${ENV_PROPS[@]}" \
            -- "$@"
        ;;
    limited_write)
        # ProtectSystem=full：/usr /boot /etc 只读，/var/log 等运行目录可写。
        # 注意：仅 ProtectHome 不能禁写 /etc（ProtectHome 只覆盖 /home /root /run/user）；
        # 要"禁写 /etc、放行 /var/log"必须用 ProtectSystem=full（strict 会连 /var 也只读）。
        exec "$SYSTEMD_RUN" --pipe --wait --collect --quiet \
            "${COMMON_PROPS[@]}" \
            -p ProtectSystem=full \
            "${ENV_PROPS[@]}" \
            -- "$@"
        ;;
    none)
        exec "$@"
        ;;
    *)
        echo "未知 profile: $PROFILE" >&2
        exit 1
        ;;
esac
