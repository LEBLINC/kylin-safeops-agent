#!/usr/bin/env bash
# kylin-safeops-run.sh — Kylin SafeOps Agent 沙箱唯一执行入口（PR2b-v2）
#
# 用法: kylin-safeops-run.sh <readonly|limited_write> -- <cmd> [args...]
# 由 PrivilegeExecutor 通过 sudo 调用。
#
# 安全边界（洞1/洞2 闭合）：
#   - 不接受 none profile（system.info 由 Python 直接执行、不经 wrapper）——删除攻击面死代码。
#   - inner 命令经白名单校验（见 ALLOWED_CMDS），禁 shell/解释器，杜绝经 sudo 的任意 root 执行。
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

PROFILE="${1:?用法: $0 <readonly|limited_write> -- <cmd> [args...]}"
shift
[[ "${1:-}" == "--" ]] && shift
[[ $# -eq 0 ]] && { echo "缺少命令" >&2; exit 1; }

# ---- inner 命令白名单（与 command_templates.py 对齐，OS 级逃生边界）----
# 仅允许 executor 合法使用的生产二进制；禁止 shell/解释器（sh/bash/python/perl/awk 等）。
# 即使 agent 进程被攻陷，经 sudo 也只能以 root 跑以下命令（且受沙箱约束）。
# 生产面只含 command_templates.py 的 12 个二进制，不含任何测试工具（最小权限）。
ALLOWED_CMDS=(
    /usr/bin/df
    /usr/bin/find
    /usr/bin/ps
    /usr/sbin/ss
    /usr/bin/netstat
    /usr/bin/journalctl
    /usr/bin/lsof
    /usr/bin/systemctl
    /usr/bin/sha256sum
    /usr/bin/gzip
    /usr/bin/vmstat
    /usr/bin/free
)

# 测试二进制仅在 KYLIN_SANDBOX_TEST=1 时追加（集成测试用 touch/echo/true/false）。
# 铁律：此变量仅供测试注入；生产环境绝不设置。sudoers 不传任何 env（默认 reset_env），
# 故经真实 sudoers 调用时本分支天然不生效——生产面永不含测试工具。
if [[ "${KYLIN_SANDBOX_TEST:-}" == "1" ]]; then
    ALLOWED_CMDS+=(
        /usr/bin/touch
        /usr/bin/echo
        /bin/true
        /bin/false
    )
fi

CMD="$1"
ALLOWED=false
for allowed in "${ALLOWED_CMDS[@]}"; do
    [[ "$CMD" == "$allowed" ]] && ALLOWED=true && break
done
if [[ "$ALLOWED" != "true" ]]; then
    echo "命令不在白名单: $CMD" >&2
    exit 1
fi

# ---- 逐参数校验（之七十五 H-1）------------------------------------------
# 首 argv 白名单只保证"跑哪个二进制"，不保证"用它做什么"。find 和 systemctl
# 自带把只读命令变成任意执行/破坏的开关：
#   find <path> -exec rm -rf {} \;   → 白名单里的 find 变成任意命令执行
#   systemctl mask sshd              → 白名单里的 systemctl 变成拒绝服务
# 二者都能在不换二进制的前提下越过白名单语义，故必须按命令逐参数校验。
#
# 误伤边界（对齐 command_templates.py + privilege_executor._tool_specific_argv）：
#   find      合法参数仅 <path> 与 -type/-printf/-name（大小文件扫描各一套）
#   systemctl 合法动词仅 show（service.status）/ restart（service.restart）
#   其余命令的 flag 全部由模板硬编码，不接受调用方注入
reject() {
    echo "参数被拒（H-1 逐参数校验）: $1" >&2
    exit 1
}

case "$CMD" in
    /usr/bin/find)
        # find 的动作类谓词一律拒——它们让 find 具备执行/删除能力。
        # 用精确匹配而非模式匹配：-execdir/-okdir 等变体逐一列出，避免
        # "-exec*" 这类通配把未来新增的只读谓词也误伤。
        #
        # 只读谓词白名单：除 <path> 与 -type/-printf/-name 的取值外，不允许
        # 任何其它 - 开头的选项（挡住未来新增的危险谓词）。
        FIND_ARGS=("${@:2}")   # 去掉 CMD 自身，只看参数
        expect_value=false
        for arg in "${FIND_ARGS[@]}"; do
            if $expect_value; then
                expect_value=false
                continue
            fi
            case "$arg" in
                -exec|-execdir|-delete|-ok|-okdir|-fls|-fprint|-fprintf|-fprint0)
                    reject "$arg（find 动作类谓词，可执行命令或删除文件）"
                    ;;
                -type|-printf|-name)
                    expect_value=true
                    ;;
                -*)
                    reject "$arg（find 仅允许 -type/-printf/-name）"
                    ;;
            esac
        done
        ;;
    /usr/bin/systemctl)
        # 动词白名单：show（只读查询）/ restart（唯一放行的变更动作）。
        # 明确拒绝 mask/disable/stop/kill/isolate 等——它们能在不换二进制的
        # 前提下把"重启某服务"升级成整机拒绝服务。
        VERB="${2:-}"
        case "$VERB" in
            show|restart) ;;
            "") reject "systemctl 缺少动词" ;;
            *) reject "$VERB（systemctl 动词仅允许 show/restart）" ;;
        esac
        # 动词之后只接受服务名/属性名，不接受选项注入（如 --signal=KILL）。
        for arg in "${@:3}"; do
            case "$arg" in
                -*) reject "$arg（systemctl 动词后不接受选项）" ;;
            esac
        done
        ;;
esac

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
    *)
        echo "未知或不允许的 profile: $PROFILE" >&2
        exit 1
        ;;
esac
