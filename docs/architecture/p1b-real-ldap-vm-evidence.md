# P1b 真 LDAP 端到端 VM 实证报告

- **状态**：✅ 全 20 组与期望一致（2026-06-20）
- **范围**：4 LDAP 用户 × 5 user_intent = 20 组合，五道闸全链 + 真 OpenLDAP server + 真 ldap3 客户端
- **环境**：麒麟 V11（LoongArch）+ OpenLDAP 2.6.5 + Python 3.11.6 + ldap3 2.9.1
- **对应工单**：L 发"P1b 真 LDAP server 端到端 VM 实证"
- **关联**：[ADR-0002](../ADR/0002-stage5-real-llm-kylin-vm-closure.md) 阶段5 真 LLM 收口（fixture planner 复用其五道闸地板）

## 1. 背景

阶段5 真 LLM 收口（ADR-0002，dev=`e2bd033`）已坐实五道闸 + 真 LLM 端到端。
P1b 阶段 L 域合入 LdapClient 真模式（commit `8848918` + DN 归一化 `a761b8d`），
13 单元测全过但 **ldap3 模块未触网** —— 真 LDAP server 对接的最后一公里未做。

本次实证补齐：
- 在麒麟 V11 实机部署原生 OpenLDAP slapd（非 docker；公共镜像无 LoongArch）；
- 4 测试用户（alice/operator1/viewer1/auditor1）→ 4 测试组 → 4 角色（admin/operator/viewer/auditor）；
- 真 ldap3 客户端 `LdapClient` 跑通 `authenticate` + `get_user` + DN 归一化；
- 4 用户 × 5 intent = 20 组合走 fixture planner + 真策略 + 真执行 + 真审计；
- WAIT_APPROVAL 时按真 LDAP 角色走 `can_approve` 决定 approve / reject。

**为什么 fixture planner 而非真 LLM**：ADR-0002 已 5 条真 LLM 实证坐实"判定靠地板不靠 LLM 自觉"；
本轮焦点是 LDAP server + RBAC 矩阵差异化，fixture planner 提供确定性输入便于全矩阵复现。
真 LLM 路径在 stage5 已坐实，复用其地板即可。

## 2. VM 环境

| 项 | 值 |
|---|---|
| OS | 麒麟 V11（aarch64 / **LoongArch 64**） |
| Python | 3.11.6（venv `~/.venvs/kylin_ci`） |
| ldap3 | 2.9.1（pip install 到 venv） |
| OpenLDAP | `openldap-servers-2.6.5-7.ky11.loongarch64` + `openldap-clients-2.6.5-7.ky11.loongarch64` |
| 仓库 | `/home/vmuser/sandbox-verify/kylin-safeops-agent-dev/` HEAD=`feadd3e` |
| 沙箱 | `KYLIN_SANDBOX_ENABLED=1`，systemd-run + kylin-safeops 用户 + sudoers |

## 3. LDAP server 部署

### 3.1 路线选择：原生 slapd（非 docker）

L 工单初版建议 `osixia/openldap:1.5.0` docker。复核发现 osixia 及主流镜像**无 LoongArch 构建**，
切回原生 `dnf install openldap-servers`。OpenLDAP 2.6.5 相对工单假设的 2.4 时代有 3 处差异：

1. `back_mdb` 后端**静态编译进 slapd**，slapd.conf 不能再 `moduleload back_mdb.la`；
2. systemd unit `ExecStart=/usr/sbin/slapd -u ldap -h "..."` **无 `-f` 无 `-F`**，
   slapd 走默认查找：`/etc/openldap/slapd.d` 优先 → fallback `/etc/openldap/slapd.conf`；
3. `ExecStartPre=/usr/libexec/openldap/check-config.sh` 要求 `SLAPD_CONFIG_FILE` 在 `/etc/sysconfig/slapd`
   或 `SLAPD_CONFIG_DIR` 二选一，缺则 `exit 1` 拒启。

### 3.2 文件清单

仓库 `deploy/sandbox/ldap_server/`：

| 文件 | 用途 |
|---|---|
| `slapd.conf` | 静态配置：mdb + memberof overlay + cn=admin rootdn + ACL（匿名禁查、self 读自己、users 读全树） |
| `init.ldif` | 4 用户 + 4 组初始数据；user/root 口令全占位 `__USER_PW_HASH__` / `__ROOTPW_SSHA__` |
| `README.md` | VM runbook：dnf 装 → slappasswd → /tmp 工作副本 sed → slapadd 离线灌库 → 起 slapd → 烟测 |

**S9 合规**：仓库零口令字面 / 零 hash 字面。所有口令**仅 shell export**，sed 替换在 `/tmp` 工作副本上做，
`git status` 始终 clean。

### 3.3 memberof overlay 反向链补建

`slapadd` 离线灌库**不触发** memberof overlay 反向链填充（已知限制）。
解决：灌完后在线 `ldapmodify` 对每个组做 `delete member: ... ; add member: ...`，
让 overlay 重算反向链，alice/operator1/viewer1/auditor1 的 memberOf 属性才到位。
DN 归一化路径（L commit a761b8d 的 `_normalize_group_name`）在真 LDAP 全 DN 返回值上字节级 work。

## 4. 20 组实证矩阵

### 4.1 跑法

```bash
# 在 VM 仓库根
source ~/.venvs/kylin_ci/bin/activate
source /tmp/kylin_env.sh   # 9 个 KYLIN_LDAP_* + KYLIN_SANDBOX_ENABLED
python3 /tmp/p1b_harness.py 2>&1 | tee /tmp/p1b_real_ldap_vm.log
```

`p1b_harness.py` 关键逻辑：
- 每组先 `LdapClient.authenticate(user, "KylinTest123!")` 真打 OpenLDAP server；
- 真模式拿 `LdapClient.get_user(user).roles` 验角色映射；
- `build_e2e` 用 fixture planner 装配真策略 + 真执行 + 真审计 + 真 sqlite 哈希链；
- `WAIT_APPROVAL` 时按真 LDAP 角色走 `can_approve(role, pending)` 决定 `resume(approved=True/False)`；
- 末尾汇总 20 行矩阵 + 与期望对照（通过 / 不符）。

### 4.2 结果矩阵

| user (role) | I1 disk.usage R1 | I2 inject rm -rf / | I3 lsof /etc/shadow | I4 service.restart R3 | I5 log.compress_rotate R2 |
|---|---|---|---|---|---|
| **alice** (admin) | FINISHED · 9 · ✓ | REJ injection · 2 · ✓ | REJ policy_deny · 5 · ✓ | FINISHED approve · 10 · ✓ | FINISHED approve · 10 · ✓ |
| **operator1** (operator) | FINISHED · 9 · ✓ | REJ injection · 2 · ✓ | REJ policy_deny · 5 · ✓ | **REJ rbac** · 6 · ✓ | FINISHED approve · 10 · ✓ |
| **viewer1** (viewer) | FINISHED · 9 · ✓ | REJ injection · 2 · ✓ | REJ policy_deny · 5 · ✓ | **REJ rbac** · 6 · ✓ | **REJ rbac** · 6 · ✓ |
| **auditor1** (auditor) | FINISHED · 9 · ✓ | REJ injection · 2 · ✓ | REJ policy_deny · 5 · ✓ | **REJ rbac** · 6 · ✓ | **REJ rbac** · 6 · ✓ |

> 单元格格式：`state · record_count · verify_chain.valid`
> `REJ rbac` = `state=REJECTED, rejected_cause=user_reject, rbac_decision=reject_rbac`

### 4.3 汇总判定

- **通过 20 / 20，不符 0**（harness 末尾 "全部 20 组与期望一致"）
- **verify_chain.valid 全 true**（4 用户 × 5 intent = 20 个独立 trace 链）
- **`all_is_untrusted=true`** 在所有 FINISHED 的 7 个组合上成立（结果闸密封 wrap_token）
- LDAP `authenticate` 4/4 用户 `ldap_auth_ok=true`，`ldap_groups` 返回**完整 DN**
  （`cn=kylin-admins,ou=groups,dc=kylin,dc=test` 等），经 `_normalize_group_name` 归一化后查 role map → 角色映射 4/4 全对

## 5. 五道闸逐条坐实

复用 ADR-0002 五道闸口径，本次实证补充 RBAC 维度数据：

1. **输入闸（detect_injection）**：4 用户 × `rm -rf /` 注入样本 → 4/4 `REJECTED, cause=injection, record_count=2`。
   `orchestrator.plan()` **之前** return，fixture planner 根本没被调，**与用户角色无关**。
2. **策略闸（PolicyEngine FILE001）**：4 用户 × `lsof /etc/shadow` → 4/4 `REJECTED, cause=policy_deny, record_count=5`。
   FILE001 deny 路径短 record_count=3-6 与 ADR-0002 stage4-B 一致；**与用户角色无关**。
3. **确认闸 + RBAC（can_approve）**：
   - I4 service.restart 要 admin（R3）：alice 1/1 通过 → FINISHED；operator1/viewer1/auditor1 3/3 RBAC 拒批 → REJECTED；
   - I5 log.compress_rotate 要 operator（R2）：alice/operator1 2/2 通过 → FINISHED；viewer1/auditor1 2/2 RBAC 拒批 → REJECTED。
   `pending_approval_role` 字段证明 PolicyEngine 输出 approval_role 与 RBAC 表口径一致（admin/operator）。
4. **结果闸（is_untrusted=true）**：所有 FINISHED 的 7 组（1+1+1+1+1+1+1 = alice 3 + operator1 2 + viewer1 1 + auditor1 1）的 `tool_result_count=1` 且 `all_is_untrusted=true`，
   wrap_token 密封铁字节。
5. **审计闸（verify_chain）**：20 trace 全 `valid=true`，record_count 按路径长度落点：
   - injection 路径 2（received + rejected）；
   - policy_deny 路径 5；
   - RBAC reject 路径 6（多 await_approval）；
   - R1 read-only FINISHED 路径 9；
   - WAIT-APPROVAL + approve + FINISHED 路径 10（多 await + approved）。

## 6. RBAC 矩阵与 can_approve 表对照

`backend/app/security/rbac.py:_APPROVABLE`：

```python
_APPROVABLE = {
    "operator": frozenset({"operator"}),
    "admin":    frozenset({"operator", "admin"}),
}
```

实证矩阵 RBAC 行：

| 角色 → 期望 approval_role | admin (R3) | operator (R2) |
|---|---|---|
| admin (alice) | ✓ approve | ✓ approve |
| operator (operator1) | ✗ reject_rbac | ✓ approve |
| viewer (viewer1) | ✗ reject_rbac | ✗ reject_rbac |
| auditor (auditor1) | ✗ reject_rbac | ✗ reject_rbac |

字节级符合 `_APPROVABLE` 表 + 失败关闭原则（viewer/auditor 未列表 → 一律拒）。

## 7. S9 合规与 git status 干净

- 所有口令仅 shell `export` 后 `source /tmp/kylin_env.sh`，**未写入 git tracked 文件**；
- `slapd.conf` 中 `rootpw` 占位 `__ROOTPW_SSHA__`，`init.ldif` 中 `userPassword` 占位 `__USER_PW_HASH__`，
  实际 SSHA hash 由 runbook 在 `/tmp` 工作副本上 sed 替换；
- harness `p1b_harness.py` 仅放在 VM `/tmp` 不进 repo；env 文件 `/tmp/kylin_env.sh` 同理；
- VM 上 `git status` 干净（仅跑不改）。

## 8. 与 ADR-0002 阶段5 实证的差异与互补

| 维度 | ADR-0002 阶段5 | P1b 本次实证 |
|---|---|---|
| LLM | 真端点 qwen3.7-max | fixture planner（确定性，便于全 20 组对账） |
| LDAP | 未涉及（用 KYLIN_LDAP_MOCK） | 真 OpenLDAP 2.6.5 + 真 ldap3 客户端 |
| RBAC | 单元测断言（can_approve unit-level） | 4 真 LDAP 用户 × R2/R3 × approve/reject 端到端 |
| 五道闸 | 5 user_intent | 20 (user, intent) 组合 |
| 沙箱 | KYLIN_SANDBOX_ENABLED=1 | 同 |
| 审计哈希链 | 5 trace | 20 trace |

互补关系：
- 阶段5 坐实"真 LLM 即使被注入也无法突破地板"；
- 本次 P1b 坐实"真 LDAP 用户的角色经 memberOf + DN 归一化映射后，
  与 RBAC 表 `_APPROVABLE` 字节级一致；不同角色在 R2/R3 上行为差异化字节级符合期望"。

两者地板**完全复用**（fixture/real LLM 切换由 `KYLIN_LLM_PROVIDER` 控制；LDAP mock/real 由 `KYLIN_LDAP_MOCK` 控制），
切换某一侧不改另一侧行为。

## 9. 复现 / Re-run

VM 上：

```bash
cd /home/vmuser/sandbox-verify/kylin-safeops-agent-dev
source ~/.venvs/kylin_ci/bin/activate
# 重起 LDAP（详见 deploy/sandbox/ldap_server/README.md）
sudo systemctl start slapd
# 加载 9 env
source /tmp/kylin_env.sh
# 跑 harness
python3 /tmp/p1b_harness.py 2>&1 | tee /tmp/p1b_real_ldap_vm.log
# 末尾期望："通过 20 / 20, 不符 0"
```

`p1b_harness.py` 完整脚本不提交进 repo（避免 scripts/ 越界）；harness 源码归档在 D
工作目录 `md/D/p1b_harness.py`，跑前上传到 VM `/tmp/`。

## 10. 后续 / Backlog

- **L 域 follow-up（非阻 D 实证）**：`test_ldap_client.py` 6 真模式 mock 用例仍用裸名 `_V(["kylin-admins"])`，
  未覆盖 `_normalize_group_name` 真 DN 路径。建议补 1 个 `test_real_get_user_memberOf_full_dn_normalized` 用例
  喂入完整 DN，断言归一化到裸名后映射 role。
- **生产 AD 大小写敏感风险**（边界，非本轮范围）：`_normalize_group_name` 用 `dn.lower()` 判 `cn=` 前缀但返回保留 case 的裸名；
  生产 AD 若返回 `CN=KYLIN-ADMINS,...` 则裸名出来是 `KYLIN-ADMINS`，env 键 `kylin-admins` 不匹配。
  当前沙箱 slapd 全小写规避；生产前 L 域需考虑大小写归一。
- **反代端到端 HTTP 路径**：本次实证走 Python 直调 `LdapClient` + `Orchestrator`，未经 nginx 反代 Basic Auth。
  反代→LDAP 接入已在 X 域 commit `25c66bf` + L 域 a8848918 合入，下次端到端可叠加。
