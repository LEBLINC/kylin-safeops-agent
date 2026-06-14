#!/usr/bin/env bash
# verify-sandbox-on-vm.sh — Kylin SafeOps Agent 沙箱 VM 到手即跑验证清单
#
# 用途：PR2b §9 列出的麒麟 VM 待验证项，codify 成一键脚本。在已部署 wrapper
#       （/usr/local/sbin/kylin-safeops-run.sh）+ sudoers 的目标机上以 root 运行，
#       逐项核对沙箱真实行为（路径/写拒绝/dbus 可达性/开销/洞1洞2 复证）。
#
# 用法：sudo ./verify-sandbox-on-vm.sh [目标服务]
#       目标服务默认 cron.service，可传安全服务覆盖（勿用 sshd/network，避免断连）。
#
# 输出：每项 [PASS] / [FAIL] / [WARN] + 说明，末尾汇总 N passed / M failed / K warnings。
# 退出码：有 FAIL → 1；仅 WARN/全 PASS → 0（service.restart 等未知项不阻断）。
#
# 关于 KYLIN_SANDBOX_TEST：写拒绝/开销探测用 touch、/bin/true 等测试二进制，它们已
# 从生产白名单分离，仅在 KYLIN_SANDBOX_TEST=1 时放行。本脚本以 root 直接调用 wrapper
# 时显式注入该变量，以便真正触达 systemd 沙箱层做写拒绝判定；而洞1/洞2 复证刻意走
# 真实 sudoers（sudo -n，env 被清理）以证明生产面边界。
#
# 只读探测为主；写操作仅用 $RANDOM 临时路径并即时清理。
set -euo pipefail

WRAPPER=/usr/local/sbin/kylin-safeops-run.sh
EXPECT_SYSTEMD_RUN=/usr/bin/systemd-run
EXPECT_SUDO=/usr/bin/sudo
TARGET_SVC="${1:-cron.service}"

PASS=0
FAIL=0
WARN=0

pass() {
    PASS=$((PASS + 1))
    echo "[PASS] $*"
}
fail() {
    FAIL=$((FAIL + 1))
    echo "[FAIL] $*"
}
warn() {
    WARN=$((WARN + 1))
    echo "[WARN] $*"
}

# 以 root 直接调用 wrapper，并注入 KYLIN_SANDBOX_TEST=1（放行测试二进制，
# 以便探测 systemd 沙箱写拒绝/开销）。返回 wrapper 退出码。
run_test_mode() {
    KYLIN_SANDBOX_TEST=1 "$WRAPPER" "$@"
}

echo "=== Kylin SafeOps 沙箱 VM 验证（wrapper=$WRAPPER, 目标服务=$TARGET_SVC）==="

if [[ ! -x "$WRAPPER" ]]; then
    echo "[FATAL] 未找到可执行 wrapper：$WRAPPER（请先部署并 chmod 0755）" >&2
    exit 1
fi

# ---- 1. 路径探测：实际绝对路径与 wrapper 硬编码比对 ----
echo "--- [1] 路径探测 ---"
actual_sr="$(command -v systemd-run || true)"
actual_sudo="$(command -v sudo || true)"
if [[ "$actual_sr" == "$EXPECT_SYSTEMD_RUN" ]]; then
    pass "systemd-run 路径匹配硬编码：$actual_sr"
else
    warn "systemd-run 实际路径 '$actual_sr' != 硬编码 '$EXPECT_SYSTEMD_RUN'，需校正 wrapper"
fi
if [[ "$actual_sudo" == "$EXPECT_SUDO" ]]; then
    pass "sudo 路径匹配硬编码：$actual_sudo"
else
    warn "sudo 实际路径 '$actual_sudo' != 硬编码 '$EXPECT_SUDO'，需校正"
fi

# ---- 2. readonly 写 /etc → 必须被拒 ----
echo "--- [2] readonly 写 /etc 拒绝 ---"
ro_etc="/etc/kylin-verify-$RANDOM"
if run_test_mode readonly -- /usr/bin/touch "$ro_etc" 2>/dev/null; then
    fail "readonly 竟允许写 /etc（$ro_etc）——ProtectSystem/ReadOnlyPaths 未生效"
    rm -f "$ro_etc" 2>/dev/null || true
else
    pass "readonly 写 /etc 被拒（内核级只读生效）"
fi

# ---- 3. limited_write：禁 /etc、允许 /var/log ----
echo "--- [3] limited_write 写边界 ---"
lw_etc="/etc/kylin-verify-$RANDOM"
if run_test_mode limited_write -- /usr/bin/touch "$lw_etc" 2>/dev/null; then
    fail "limited_write 竟允许写 /etc（$lw_etc）"
    rm -f "$lw_etc" 2>/dev/null || true
else
    pass "limited_write 写 /etc 被拒"
fi
lw_log="/var/log/kylin-verify-$RANDOM"
if run_test_mode limited_write -- /usr/bin/touch "$lw_log" 2>/dev/null; then
    pass "limited_write 写 /var/log 允许（$lw_log）"
    rm -f "$lw_log" 2>/dev/null || true
else
    fail "limited_write 竟禁止写 /var/log（$lw_log）——profile 过严"
fi

# ---- 4. service.restart dbus 可达性（关键未知项，不阻断）----
# systemctl 是生产白名单二进制，无需测试模式。
echo "--- [4] service.restart dbus 可达性（$TARGET_SVC）---"
if "$WRAPPER" limited_write -- /usr/bin/systemctl restart "$TARGET_SVC" 2>/dev/null; then
    pass "limited_write 内 systemctl restart $TARGET_SVC 成功（sandbox 内可触达 system dbus）"
else
    warn "limited_write 内 systemctl restart $TARGET_SVC 失败——service.restart 需走 profile 例外（NoNewPrivileges/ProtectHome 可能阻断 dbus）"
fi

# ---- 5. 启停开销粗测 ----
echo "--- [5] 启停开销 ---"
start_ns="$(date +%s%N)"
if run_test_mode readonly -- /bin/true 2>/dev/null; then
    end_ns="$(date +%s%N)"
    elapsed_ms=$(((end_ns - start_ns) / 1000000))
    if [[ "$elapsed_ms" -lt 500 ]]; then
        pass "wrapper readonly -- /bin/true 耗时 ${elapsed_ms}ms (<500ms)"
    else
        warn "wrapper readonly -- /bin/true 耗时 ${elapsed_ms}ms (>=500ms)，瞬态 service 启停偏慢"
    fi
else
    fail "wrapper readonly -- /bin/true 执行失败（systemd-run 不可用或属性冲突）"
fi

# ---- 6. 洞1/洞2 实机复证（经真实 sudoers，env 被清理）----
# 洞1：none 用生产白名单二进制 df，确保通过白名单后由 profile case 拒绝（证 none 分支已删）。
# 洞2：/bin/sh 永不在任何白名单，由白名单层拒绝（证禁 shell/解释器）。
echo "--- [6] 洞1/洞2 复证 ---"
if sudo -n "$WRAPPER" none -- /usr/bin/df >/dev/null 2>&1; then
    fail "洞1 复现：wrapper 竟接受 none profile"
else
    pass "洞1 复证：none profile 被拒（已删除 none 分支）"
fi
if sudo -n "$WRAPPER" readonly -- /bin/sh -c "echo pwned" >/dev/null 2>&1; then
    fail "洞2 复现：wrapper 竟允许 /bin/sh"
else
    pass "洞2 复证：非白名单 /bin/sh 被拒"
fi

# ---- 汇总 ----
echo "=== 汇总：${PASS} passed / ${FAIL} failed / ${WARN} warnings ==="
[[ "$FAIL" -eq 0 ]]
