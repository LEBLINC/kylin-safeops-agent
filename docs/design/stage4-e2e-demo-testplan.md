# 阶段4 端到端 Demo 落地方案（L 执行窗口）

> 基线：**dev = `c6ca02f`**（2026-06-16，阶段3 收口 + 3b+ADR-0001 已合入）。
> Owner：L（执行窗口）。协作者：D 域保持不动、X 域不动。
> 铁律（重申开场白 §8）：pytest 真报、脚本真跑、注释不撒谎、只报本分支真 diff、不自 commit/push。

---

## 0. 目标与口径

**唯一目标**：在已闭合的地板（dev=c6ca02f）上，证明**判定 + 执行 + 审计 + 审批 + 沙箱 + 认证**全链在 demo 场景下走通；每条五道闸都跑出"可观察证据"。

**不做什么**：
- 不动 D 域（security/executor/audit/db）——本次需求 L 域内闭合。
- 不动 X 域（frontend/deploy/proxy/mcp_servers/rca）。
- 不接真 LLM（阶段 5 单独做）——本阶段沿用 fake planner（_demo_common.scripted_llm）。
- 不录真 VM 视频（需 D 域 VM 访问权限）——本机真跑部分全部上"真"（非桩），VM 才能跑的部分诚实标"待 VM 验证"。

**对外口径（成功后）**：判定+执行+审计+审批+沙箱+认证 全链在 fake planner 驱动下走通 demo 四场景剧本，零桩漏真。

---

## 1. 场景剧本（与开场白 §6.1 + VM 清单阶段4 对齐）

| # | 场景 | 触发 | 五道闸行为 | 期望终态 | 沙箱依赖 |
|---|------|------|------------|----------|----------|
| A | **注入红队（输入闸 deny）** | user_intent 含 D-10 golden high 命中样本 | ① D-10 high→deny（拦在 plan 前） | REJECTED, cause="injection" | 无 |
| B | **策略闸 deny（/etc/shadow 工具试图访问）** | fake planner 强行产 `disk.usage` 类工具 + args.path="/etc/shadow"（注：本架构里走 FILE001 拒绝的典型是含 `/etc/shadow` 的命令参数；用 file.read 或类似允许执行的工具做载体） | ① D-10 放行 ② 真 PolicyEngine 命中 FILE001→deny | REJECTED, cause="policy_deny" | 无 |
| C | **确认闸 resume（service.restart 沙箱内真重启 cron.service）** | fake planner 产 `service.restart` (R3 confirm/admin) | ① 放行 ② confirm ③ **真审批 = admin** ④ 真执行（沙箱内 systemctl restart cron.service） ⑤ 落库 + verify_chain valid | FINISHED | **VM 必需**（沙箱=wrapper+systemd 瞬态 service；Windows skip） |
| D | **确认闸 resume（log.compress_rotate 真写 /var/log）** | fake planner 产 `log.compress_rotate` (R2 confirm/operator) | ① 放行 ② confirm ③ **真审批 = operator** ④ 真执行（沙箱内 limited_write 写 /var/log） ⑤ 落库 + verify_chain valid | FINISHED | **VM 必需** |
| E | **结果闸 is_untrusted + 审计闸 verify_chain** | 同 C 或 D，但额外断言 is_untrusted=True 包裹、payload 落库字段正确、verify_chain valid=True、payload 落库后可单独读出 | 五道闸全过 + 真落库 + 真链校验 | FINISHED + verify_chain valid | 真执行环境（VM 优，Windows 跑 system.info 验证） |
| F | **审计完整性篡改检出** | 在 E 的基础上，对 SqliteAuditSink 真做 UPDATE payload 改一字节 → 调 verify_chain | 链应 valid=False + reason="篡改…" + broken_seq 指向被改 seq | valid=False, reason 含"篡改" | 无（纯单元） |

**C/D 在 Windows 上沙箱会跳过真实 systemctl/gzip**——但 orchestrator→policy→approval→execute→seal→audit 链路**全真**（executor 走真 PrivilegeExecutor，Windows 沙箱 disable，命令仍真跑；systemctl 在 Windows 不存在 → exit_code 非零），属"诚实不撒谎"的 fail-fast。VM 上 KYLIN_SANDBOX_ENABLED=1 才完整闭合。

---

## 2. 实现策略

### 2.1 文件新增
| 路径 | 用途 | 域 |
|------|------|----|
| `scripts/demo_stage4_e2e.py` | 阶段4 端到端 demo 主入口（CLI：跑 A–F 全部或子集） | L |
| `scripts/demo_stage4_common.py` | 装配（真 PolicyEngine + 真 PrivilegeExecutor + 真 SqliteAuditSink:memory: + fake LLM），复用 `_demo_common` 风格 | L |
| `backend/tests/test_demo_stage4_e2e.py` | A–F 6 个端到端用例（pytest 真跑，不是"演示页脚"） | L |
| `docs/design/stage4-e2e-demo-acceptance-report.md` | 实跑结果汇总（场景/期望/实跑/diff/给 D·X 衔接） | L |
| `docs/design/stage4-e2e-demo-testplan.md` | **本文件** | L |

### 2.2 复用既有
- `backend.app.security.PolicyEngine(DEFAULT_POLICY, registry)` — 真策略闸。
- `backend.app.executor.PrivilegeExecutor(sandbox_enabled=...)` — 真执行闸。
- `backend.app.audit.SqliteAuditSink(":memory:")` — 真审计落库（内存库，不污染工作树）。
- `backend.app.security.injection_detector.detect_injection` — 真输入闸（orchestrator 内部调，不需 L 直调）。
- `backend.app.contracts.audit.compute_curr_hash / canonical_json` — 哈希链契约。
- `backend.app.security.rbac.can_approve` — RBAC 纯函数。
- `mcp_servers.os_ops.all_specs()` — 真工具集。
- `_demo_common.scripted_llm` — fake planner（不联网）。
- `backend.tests.conftest` — 既已 `:memory:` 钉死审计库 + dev 模式认证放行（审阅窗口已固）。

### 2.3 关键约束（C3 边界）
- **不修改** D 域（security/executor/audit/db）任何文件。
- **不修改** 既有 scripts/_demo_common.py（向后兼容，阶段 4 demo 用独立脚本）。
- **不修改** 既有 tests（test_demo_playbook 等保持原口径；阶段 4 用新 test 文件避免回归混淆）。
- **不修改** mcp_servers/os_ops（X/D 域交接过的，不动）。
- 新增脚本**只 import** 既有真件做装配，不重写。

### 2.4 端到端用例断言原则
- **不**写"成功状态"的软断言（如"没崩就行"）。
- **必须**写五道闸各自的硬断言：
  - ① 输入闸：终态为 REJECTED 且 audit payload 含 `input_gate: deny` + `category`/`pattern_id`。
  - ② 策略闸：终态为 REJECTED 且 audit payload 含 `decision: deny` + 真策略 matched_rules 含 FILE001。
  - ③ 确认闸：先 WAIT_APPROVAL、resume(True) 后 FINISHED、audit payload 含 `approval_required: True`。
  - ④ 结果闸：ToolResult.is_untrusted=True（接口本身强制，断言 orchestrator 不裸调 executor）。
  - ⑤ 审计闸：verify_chain valid=True、record_count 与 orchestrator 产出的 _append_audit 次数一致、seq 连续、prev_hash 链。
- **额外** 场景 F：手动 SQL `UPDATE payload SET ...` → verify_chain valid=False + broken_seq 指到被改 seq + reason 含"篡改"。

---

## 3. 跑测流程

### 3.1 本机（Windows, kylin_ci）
```powershell
cd D:\Developer_tools\PycharmProjects\kylin
git add -N .
$env:PYTHONUTF8="1"
conda run -n kylin_ci --no-capture-output pytest backend/tests/test_demo_stage4_e2e.py -v
```

### 3.2 端到端主入口（开发者手跑）
```powershell
conda run -n kylin_ci python -m scripts.demo_stage4_e2e --scenarios A,B,E,F
conda run -n kylin_ci python -m scripts.demo_stage4_e2e --all
```

### 3.3 麒麟 VM
```bash
KYLIN_SANDBOX_ENABLED=1 conda run -n kylin_ci python -m scripts.demo_stage4_e2e --scenarios A,B,C,D,E,F
```
（VM 才完整跑 C/D 的 systemctl/gzip 真执行；本机只跑 A/B/E/F 四场景。）

### 3.4 四道闸（CI 口径）
```powershell
$env:PYTHONUTF8="1"
conda run -n kylin_ci --no-capture-output pre-commit run --all-files
```

---

## 4. 验收报告大纲（`docs/design/stage4-e2e-demo-acceptance-report.md`）

```
## 0. 摘要
- 真跑真数（pytest passed/skipped）；本机 vs VM 差异。
## 1. 场景 A 注入红队
- 输入样本 / 输入闸命中 / 终态 / 审计落库 4 字段
## 2. 场景 B 策略闸 deny
- 工具+args / 真策略 matched_rules / 终态 / 审计落库
## 3. 场景 C service.restart 真重启（待 VM）
- 本机执行结果（exit_code≠0 因无 systemctl） / VM 期望值
## 4. 场景 D log.compress_rotate 真写 /var/log（待 VM）
- 同上
## 5. 场景 E 结果闸 + 审计闸
- is_untrusted 断言 / verify_chain valid=True / record_count
## 6. 场景 F 审计完整性
- 篡改手法 / verify_chain 报出 / broken_seq / reason
## 7. git status / diff / 给 D·X 的衔接
## 8. 遗留与 backlog
- VM 真跑（需 D 域 VM 访问权限）
- 阶段 5 真实 LLM 接入（独立增量）
```

---

## 5. 协作与提交纪律

- 本工单执行窗口**不自行 commit/push**。
- 改完写交接进 `审阅交接.md`：
  - 改了什么 / S·C·E 自检 / 四道闸结果 + **亲跑 pytest 真数** / git status / 建议 commit message / diff 命令 / 给 D·X 的衔接说明 / 遗留。
- 审阅 PASS 后由 L 统一 commit+push。
- 严格区分：本机真跑（场景 A/B/E/F）vs VM 必跑（场景 C/D 沙箱内真执行）——本机跑 ≠ VM 跑；后两者诚实标"待 VM 验证"，不假报 PASS。

---

最后更新：2026-06-16，dev=c6ca02f 收口后。
