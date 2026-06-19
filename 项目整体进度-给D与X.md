# Kylin SafeOps Agent — 项目整体进度快照（给 D / X）

> 维护：L（集成 + 审阅窗口）。基线：**dev = `cc4b527`（origin 已同步）**。日期：2026-06-16。
> 用途：让 D / X 看清当前整条线在哪、自己下一步做什么。详细决策见 `集成对齐备忘.md`。
> ★本快照自 dev=`cc4b527` 起为**当前权威**；§4 决策记录是历史沉淀（按编号勿翻案）；§2 旧版"已入库内容"按时间倒序补到 §6。

---

## 0. 一句话状态

**「内网 only 正式解除」**（阶段3 五项 + 审计 3a 全绿，dev=cc4b527）。对外口径可坐实：**判定+执行+审计(哈希链 verify valid)+审批认证(HMAC 签名身份)+沙箱(data_source=real)+反代签名认证**全链在麒麟 V11 实机闭合。
待 merge（已审 PASS）：3b retention/rotation(`b94fd38`) + ADR-0001 SQLite 选型冻结(`dd16190`)。backlog：阶段4 端到端 demo、阶段5 真实 LLM 接入。

## 1. 五道闸 + 认证 + 沙箱 + 采集 真假快照（dev=cc4b527）

| 项 | 状态 | 说明 |
|---|---|---|
| ①输入闸 | 🟢 真 | LLM 产结构化 Intent + 对抗降级；**D-10 injection_detector 已接 orchestrator**（high→deny 拦在 plan 前 / medium→审计标记）；只覆盖直接注入(user_intent)，间接注入由 ④结果闸中和 + ②策略闸 deny 兜底（决策记录） |
| ②策略闸 | 🟢 真 | RuleBasedPolicyEngine，API 实证 deny /etc/shadow |
| ③确认闸 | 🟢 真 | WAIT_APPROVAL+resume；can_approve fail-closed；**审批认证出自反代签名身份(auth.py HMAC)**；拒批放宽(任何已认证者可取消) |
| ④结果闸 | 🟢 真 | seal_result + wrap_token 归一 + 回喂定界中和 |
| ⑤审计闸 | 🟢 真 | 哈希链 + SqliteAuditSink lifespan 单例落库 + verify_chain；**路径硬化 3a 已合**（KYLIN_AUDIT_DB 绝对路径 fail-closed + 0600/0700）|
| 🔐全量端点认证 | 🟢 真 | verify_token mode-aware（proxy 全端点要求反代签名 fail-closed 401 / dev 放行）；whoami 端点；签名 CLI oracle |
| 🛡️systemd 沙箱 | 🟢 真(VM验证) | 瞬态 service(--pipe --wait --collect 非 scope)；wrapper 唯一入口+属性硬编码+inner 白名单(洞1洞2闭合)；**麒麟 VM 实证写拒绝/service.restart dbus 可达/洞复证 9/0/0**；默认 KYLIN_SANDBOX_ENABLED=1 才开 |
| 📊overview 真采集 | 🟢 真(VM验证) | disk/zombie/cpu(vmstat)/mem(free) 四项真→**data_source=real**(VM 实证)；缺真诚实降级 partial/stub |
| 🔁反代签名认证 | 🟢 真(VM验证) | L:whoami+systemd(127.0.0.1) + X:deploy/proxy/proxy.py(Basic Auth→HMAC 注入 4 头+剥客户端伪造头+SSE 透传+fail-closed 401)。**阶段3 VM 五项联合验收全绿（2026-06-16）** |
| 终态 rejected 事件 | 🟢 真 | stream.py rejected EventType + orchestrator 两路 emit；前端三值 union 已合 |

## 2. 当前 dev 已入库内容（dev=cc4b527，由近及远）

- `cc4b527` X 反代+whoami 身份过渡（匿名放行漏洞修复 fail-closed+WWW-Authenticate）
- `a47780b` proxy.py 401 响应补 WWW-Authenticate 头
- `3d00412` L whoami+sign CLI+systemd app 单元（阶段3 L 侧）
- `4e61acc` 审计库 3a（KYLIN_AUDIT_DB 绝对路径+0600/0700）
- `54c4a2d` 注入攻击 demo 终版（直接注入 echo 版）
- `45dfa5a` X Dashboard 三态（types data_source union + partial 徽标 + 诚实降级）
- `ce6ca9f` lsof 路径校准（/usr/sbin→/usr/bin 三处）
- `3a8b21a` PR2b hygiene（白名单分离+VM 验证脚本）
- `d755f1b` 沙箱启用接线（build_gateway 按 platform+env 传 sandbox_enabled）
- `c7d66e5` config.diff 在 mcp 层聚合
- `49d4914` L overview cpu/mem 真源接线
- `e4a5c25` D overview cpu/mem 模板+profile+白名单
- `812c7c6` verify_token 全量端点认证（mode-aware fail-closed）
- `6b5fecb` verify_token mode-aware 全量认证
- `50dbfcf` RBAC 反代签名身份（决策⑨ 方案a）
- `ee43dc3` D-10 输入闸（injection_detector+红队 golden）
- `5267560` 接线里程碑（甲审计单例+乙 Executor 切真+丙 overview 方案b+丁 RBAC fail-closed）

更早的 commit / PR1-3 / Executor PR2 / L-6 方案B / RCA / mcp 运行时依赖移除 / constraints.txt 等详见 `审阅交接.md` 历次留痕。

## 3. 各人下一步

### D — ✅ 阶段3 D 域全交付；3b+ADR 已审 PASS 待 merge
- ✅ **3a 审计库硬化**（4e61acc）：KYLIN_AUDIT_DB 绝对路径+0600/0700+chmod 失败 log 不抛；VM 实机复证 6a/b/c 全过。
- ✅ **3b 审计库 retention/rotation**（b94fd38，待 merge）：终态闸按 trace 整迁+带外 CLI+先验后删+INSERT OR IGNORE 修复入；19 用例测试全过；零回归。
- ✅ **ADR-0001 SQLite 选型冻结**（dd16190，待 merge）：四硬约束（LoongArch/单机/哈希链/最小信任面）+ 确认前提+revisit 条件；与 `集成对齐备忘.md:515-529` 拍板内容字面一致。
- **D 域 backlog（非阻断）**：反代占位 Basic Auth 上线前换真 SSO/LDAP（X 域登记）；文档/README 后续补充 retention CLI 用法示例。

### X — ✅ 阶段3 X 域全交付（cc4b527）；待换真 SSO/LDAP
- ✅ 反代签名 sidecar（proxy.py Basic Auth→HMAC 注入 4 头+剥客户端伪造头+SSE 透传+fail-closed 401）；**匿名放行漏洞已修闭合**（a47780b）。
- ✅ 前端三态适配（types data_source 字面 union + partial 徽标 + 诚实降级）+ 注入 demo 终版（直接注入 echo）+ 前端 whoami 身份过渡（App.vue onMounted fetchWhoami + chat.ts currentUser/Roles 静默降级 viewer + .env.production 移除 VITE_CURRENT_USER_ROLE + ChatView 展示真实 user）。
- **X 域 backlog（**非阻断**）**：反代占位 Basic Auth（不校验密码，只映射角色）上线前替换真 SSO/LDAP。

### L（我）— ✅ 阶段3 L 域全交付 + ✅ 阶段4 demo 本机落地（edf57aa）
- ✅ 阶段3 L 域：whoami 端点（3d00412）+ 签名参考 CLI + systemd app 单元（绑 127.0.0.1/UMask=0077/EnvironmentFile/ProtectSystem）。
- ✅ 阶段4 demo 落地（dev=edf57aa）：5 新文件严守 C3（D/X 域零改动亲跑 git diff 确证）：
  - `scripts/demo_stage4_common.py`（公共装配：真 PolicyEngine + 真 PrivilegeExecutor + 真 SqliteAuditSink(:memory:) + fake LLM）
  - `scripts/demo_stage4_e2e.py`（6 场景 demo 主入口 CLI，可子集跑/全跑）
  - `backend/tests/test_demo_stage4_e2e.py`（6 pytest 用例）
  - `docs/design/stage4-e2e-demo-testplan.md`（落地方案）
  - `docs/design/stage4-e2e-demo-acceptance-report.md`（验收报告）
- **L 下一步（按优先级）**：
  1. **阶段4 VM 端到端验证**（C/D 沙箱场景：service.restart 真重启 cron.service / log.compress_rotate 真写 /var/log）—— D 域 VM 跑通 `KYLIN_SANDBOX_ENABLED=1 python -m scripts.demo_stage4_e2e --scenarios C,D` → verified_summary="ok" 即为终验。
  2. **★阶段5 真实 LLM 接入**（最安全攸关，跑在已验证地板上，刻意最后）：`get_llm` provider 一处切换（fake→真，build_e2e 已预留 `use_real_llm: bool` hook 点直接扩展）+ 真 LLM 客户端 + S3 schema 校验+重试在位 + 真 LLM 下重跑 D-10 红队 golden。

## 4. 关键决策（已拍板，勿翻案）

1. **Executor 接线放在 D 的 PR3 之后**：真执行与真审计一起到位，避免"真执行却无真审计"中间态。✅ 已落地（dev=812c7c6）。
2. **L-6 = 方案B**（新增 rejected EventType），后端 + 前端（feat/x）均已落地。
3. **新增任何变更类工具**（risk≥R2 / reversible=False）**必须同步加进 `path_policy._CHANGE_TOOLS`**（否则 Executor realpath 复核漏判，O5 派生）。
4. symlink 真兜底 = PR2b systemd 沙箱（依赖麒麟 VM，D）；命令绝对路径/SAFE_ENV 待麒麟实机校准。✅ 阶段1 校准完成（ce6ca9f lsof）。
5. 协作纪律：协作者**不自行 commit**；改完写改动清单+S/C/E 自检+diff 进 `审阅交接.md`，L 审过统一提交；分支**追加 commit、勿 force-push**。
6. **★RBAC 真实认证源（决策⑨，BLOCKER-for-deployment）= 反向代理注入已验证身份**：app 只信可信代理签名头（麒麟统一认证/LDAP），角色出自已验证身份；演示态 `X-User-Role` 仅联调、上线前替换。联调期"内网 only"。✅ 阶段3 已解除。
7. **D-10 输入闸接线口径（决策⑫）**：high→deny / medium→审计标记放行（不走 confirm）；**防御纵深，只增限制不授信任，检测通过不短路下游闸**。✅ D-10 边界：只扫 user_intent；间接注入由结果闸中和+策略闸 deny 兜底。
8. **拒批放宽（决策⑬）**：`approved=False` 任何已认证者可取消，仅批准校验角色。
9. **审计字段端到端保契约原名（决策⑭）**：不做 phase→record_type/payload→content 翻译层。
10. **overview 只读探针豁免哈希链（决策⑩，方案b 有界）** + **config.diff 由 L 在 mcp 层聚合（决策⑤）** + **审计库 dev 相对/部署 env 可配置+绝对+受限权限（决策⑪）**。
11. **审计库硬化（决策⑪ 细化）**：3a 路径+权限（已合 4e61acc）+ 3b 终态闸 retention/rotation（待 merge b94fd38）= 终态 AND 早于 90 天才归档；带外 CLI（不进 lifespan）；require_absolute 绑 KYLIN_AUTH_MODE=proxy；归档默认主库同目录 + 可选 KYLIN_AUDIT_ARCHIVE_DIR 覆盖；默认 90 天 / 100MB。
12. **审计库选型 = SQLite 不引 PG**（决策 ADR-0001）：四硬约束（LoongArch 移植/单机/哈希链/最小信任面）+ 单节点前提 + revisit 条件（多节点/集中聚合/量爆炸/需 SQL 分析）；不锁死迁移路径（AuditSink Protocol）。

## 5. CI / 验证铁律（统一口径）

- 验证环境 conda `kylin_ci`（CI 镜像，Py3.11 + requirements + dev + constraints）；**禁用杂 env**。
- 验证前 `git add -N .`（防未跟踪文件假绿）；命令：
  `$env:PYTHONUTF8="1"; conda run -n kylin_ci --no-capture-output pre-commit run --all-files`。
- 四道闸：ruff / ruff-format / mypy(contracts+agent/mcp/llm/api+os_ops) / pytest（必须收集且全过）。
- 提交前确认四闸全 Passed + 无 "files were modified" + git status 干净。

---

最后更新：dev=`b421736`（2026-06-17，X 修后 stage5-prep 合入）。**"内网 only 正式解除"** + **阶段4 demo 本机+CI+X+D+VM 全收口** + **X 域阶段5 前清光合入** + **阶段5 真 LLM 接入工单 prompt 已起**。
- 阶段3（cc4b527 收口）✅ + 3b retention/rotation（4d0887e）+ ADR-0001（c6ca02f）已合 + 阶段4 demo（edf57aa）已合 + CI Linux runner fix（0065787）已合 + X demo merge（c0ad2a3）已合 + D 域 stage4 VM 修复（7b74404）已合 + record_count 路径放宽（5b2addd）已合 + D 域 stage5-prep（f9df6a6）已合 + D 域测试回填+VM 实证（94bdac9）已合 + **X 修后 stage5-prep（b421736）已合**。
- **阶段4 demo 全收口**：本机+CI Linux+X demo 前端+D 域 VM 端到端（service.restart R3+log.compress_rotate R2 都 state=FINISHED+verified_summary="ok"+record_count=10+verify_chain valid=True）。
- **阶段5 真 LLM 接入 3 步走**（L 域下次会话主任务）：
  1. **L 域接 fail_closed=True**（api.py lifespan 按 auth_mode=="proxy" 传）—— D impl 已就位（94bdac9），**L 域必须先接**
  2. **fake planner 修**（解析 user_intent 提取 tool/args，不再写死目标）
  3. **真 LLM 客户端 + 接入 + 间接注入真验**（核心，5-6 commit 拆开）
- 阶段3（cc4b527 收口）✅ + 3b retention/rotation（4d0887e）+ ADR-0001（c6ca02f）已合 + 阶段4 demo（edf57aa）已合 + **CI Linux runner fix（0065787）已合**。
- 验证：kylin_ci 四道闸全绿；pytest **435 passed / 17 skipped @ edf57aa**（基线 429 @ c6ca02f + 6 增量 = 435 数学吻合；§5 纪律无虚高）。
- 阶段1（沙箱 VM 验证+路径校准）✅；阶段2（沙箱启用+overview 真源）✅；阶段3（反代+认证+审计 3a）✅；**阶段4 demo 本机（A/B/E/F 全绿；C/D 链路真跑报 non-zero，VM 沙箱内 systemctl/gzip 真执行待 D 域 VM 实证）⬜→✅ 部分**；阶段5（真实 LLM 接入）⬜。
- **★审阅窗口 §5 红线失误留痕**：dev=edf57aa 时 CI Linux runner 场景 D 失败（原断言"非 VM = non-zero"过严，Linux root 真跑通会报 ok）→ 0065787 修复。**下次审阅涉及命令执行/平台差异的断言应主动用 WSL 模拟或 GitHub Actions 本地 dry-run 验证**。
- 阶段4 VM 端到端验证：C/D 场景在 VM 上 `KYLIN_SANDBOX_ENABLED=1 python -m scripts.demo_stage4_e2e --scenarios C,D` 跑出 `verified_summary="ok"` 即为终验。
- **X 阶段4 demo 前端已合**（c0ad2a3，X author 保留）：6 场景 A-F 补全 + 8 行空白修 + 验证链按钮 v-if 防护。
- **间接注入（日志投毒）真实叙事**：L 拍板 = **留阶段5 真 LLM 接入时一并验证**。
- **D 域阶段4 VM 修复已合**（7b74404）：log.compress_rotate 模板补 dynamic_args=["path"]；19 passed / 0 failed VM 实证 4 项全绿（B service.restart / C log.compress_rotate / D 篡改检出 / retention CLI）。**D 报告 pytest 449/17 vs 实跑 454/17 差 +5 虚高已留痕（§5 红线第三度中招）**。
- **X 域 P1 backlog**：proxy.py:83 `await client.request()` 阻塞读 body → WAIT_APPROVAL 场景永久挂死。建议改 `client.stream()` + `aiter_bytes()`。非本里程碑阻断。
- **L 域 fake planner 目标写死**（阶段5 处理）：B=nginx.service / C=/var/log/app.log 不解析 message；真 LLM 接入时一并修。
- **record_count 硬断言按路径分别放宽**（5b2addd）：B 走 REJECTED 路径 3-10，C/D/E 走 FINISHED 路径 9-10，F 篡改前 9-10。
- **D 域阶段5 前清光已合**（f9df6a6）：audit fail-closed + fake planner 参数化 + retention VACUUM + README §4 补全。**D 报告 pytest 数字这次零偏差**（§5 红线破例全过）。
- ⏳ **VM 端到端实证 backlog**（D 域跑）：`KYLIN_SANDBOX_ENABLED=1 python -m scripts.demo_stage4_e2e --scenarios C,D` 实跑 + 贴 `/tmp/stage4_cd_vm.log`
- ⏳ **L 域接 fail_closed=True backlog**（L 域）：D 报告要求 L 在 `api.py lifespan` 按 `auth_mode=="proxy"` 传 `fail_closed=True`，**L 域 stage5 启动时第一优先级**
- ✅ **D 域阶段4 VM 端到端实证 PASS**（94bdac9 之 C/D）：service.restart R3+log.compress_rotate R2 都 state=FINISHED+verified_summary="ok"+record_count=10+verify_chain valid=True。D 报告 pytest 数字零偏差（§5 红线第四度破例没中招）。
- ✅ **D 域测试回填已合**（94bdac9）：fail_closed 2 用例 + fake planner 参数化 2 用例 + 场景 E 严格断言雷移除。pytest 460/17。
- ✅ **X 域阶段5 前清光已合**（b421736）：SSE 阻塞 bug 修（client.build_request + send(stream=True)）+ README P1+NTP 节 + DemoView 色彩统一 + attack 间接注入说明 + whoami-auth 3 测 + eslint config + chat.ts 修。X 报告数字这次对（§5 红线破例）。
- ✅ **★阶段5 真 LLM 接入已合**（3c0bdca）：fail_closed 接线 + fake planner 解析 + real_client.py 347 行 + 间接注入真验 + S3 + rate limit + token cap。pytest 487/17（b421736 480 + 7 L 修过的测试）。L 报告偏差留痕（pytest 数字 +19 虚高 / ruff-format 漏报 3 文件 reformat）—— 审过 PASS 实质。
- ✅ **X 域前端样式重设计已合**（f6ded54）：全面 UI 重设计，19 文件 +1785/-1112；26 *-back.* 备份文件清除；X1_API 联调台账移出版本控制；四道闸全绿，pytest 487/17 不变；C3 边界严守（frontend-only，0 backend 文件）。X 本次 0 偏差。
- ✅ **★阶段5 真端点 e2e 驱动接通已合**（b2d1112）：`demo_stage4_e2e.py` 加 `--use-real-llm`/`--user-intent` CLI（缺参报错）+ `scenario_real()` 走五道闸全链（输入闸天然在位）；`demo_stage4_common.py` 清死占位。S9 守住（密钥全走 env）；四道闸全绿，pytest 487/17 零回归；L 本次零偏差。**真端点 httpx POST 待 D 在 VM 上配 env+密钥实跑**（阶段5 真收口最后一步）。
- ✅ **★阶段5 真收口 VM 实证 PASS + ADR-0002 拍板**（dev=`e2bd033`，2026-06-19）：D 在麒麟 V11 实机真端点 qwen3.7-max 跑 5 条 user_intent，五道闸全链闭合——3 条 FINISHED（磁盘占用/重启 R3/压缩轮转 R2）+ 2 条 REJECTED（注入 injection-2 条 / 策略 policy_deny-5 条）；5 次 `verify_chain.valid` 全 true。**输入闸在 `plan()` 之前拦死（注入仅 2 条记录）= "判定靠地板不靠 LLM 自觉"的字节级铁证**。ADR-0002 落盘 `docs/adr/0002-stage5-real-llm-kylin-vm-closure.md`（Accepted）。**D 报告第 3 条 fail_closed "仍待接" 是过时信息——已合入（commit 8f77240，3c0bdca 阶段5 合入）**，非 backlog。
- ✅ **L backlog #2 README 口径统一收口**（7762d63）：纯 docstring 改 `KYLIN_LLM_PROVIDER=fixture/real` 为实际开关，标注 `KYLIN_LLM_TEST_FIXTURE` 是 docstring 残留非实际开关。2 文件 +10/-5，**行为零变化**，pytest 501/17 = 基线，L 零偏差。L backlog 现状：#1 `?probe=true` 非阻断按需 + 阶段6 阻塞中等 X P1 SSO/LDAP。
- ✅ **另一窗口架构审阅报告处理完成**（2026-06-19）：审阅窗口亲核真值——B1 SSE use-after-close + B2 whoami `res.data` 两条**真 Blocker 落 X 域**（X 工单已起，BackgroundTask 方案 + 成功路径 vitest 用例 + vitest 接 CI）；B3 `get_llm()` 仍 fake 用 **ADR-0003** 钉死 demo-only（live API 不接真 LLM 是设计意图）。**报告 pytest 数字 482/17 经审阅窗口亲跑 = 501/17 纠正**（不是 +19 虚高，是报告作者亲跑数错）。5 条中低优治债（T4-T9）记入阶段6 backlog 防忘。
- ✅ **X 域 B1/B2/前端测试 + P1 SSO/LDAP + P2 SSE heartbeat 全部合入**（200a63c）：X 一次性 5 commit 交付——B1 SSE BackgroundTask 修（VM 复证 PASS）+ B2 whoami 一行修 + vitest 接 CI（2 用例 + ci.yml `npm test`）+ ci.yml ASCII 化 + P1 LDAP mock/真实双模式（7 测试用例全 PASS）+ P2 SSE heartbeat keepalive。pytest 501/17 零回归，四道闸全绿（autosquash 修正 BOM/类型注解后），S9 守住。**ADR-0004 钉死 KYLIN_LDAP_MOCK 默认 false** 防生产误开 mock。
- ✅ **★P1b 真 LDAP 实现合入**（8848918）：ldap3==2.9.1 依赖 + `LdapClient.authenticate/get_user` 真模式 ldap3 实现（替换 NotImplementedError）+ 13 用例（7 mock + 6 真模式 mock 全 ldap3 不触网）。5 安全红线（不区分用户不存在/密码错、防 LDAP injection 转义、size_limit=1、双超时 5s、异常吞掉）字节级全验 ✅。pytest 504/17（基线 498 + 6 真模式新增，13/13 PASS）。**真 LDAP 端到端 VM 实证 backlog**：D 在 VM 配真 ldap3 server 后重跑反代 + 五道闸。**L 报告 517/17 虚高**+ ruff 3 errors + constraints.txt 重复行 + size_limit 测试漏断 3 个 kwarg 均审阅窗口补到位。
- ✅ **O18 真 LLM planner 缺工具 schema 修复已合**（9797e43）：D VM 首跑暴露——disk.usage（无参）被 LLM 幻觉塞 path，闸2 结构校验拦死。根因：`build_system_prompt()` 从未喂工具清单 + few-shot 范例给 disk.usage 错塞 path 教错。修复：`_format_tool_catalog()` 动态渲染 + few-shot 重写为"无参/有参"双范例 + `LLMAdapter.tool_specs` 字段首调/retry 都注入。**D 零责任**（闸2 在策略前短路，PolicyEngine 未被调用——"不可信顾问"叙事实证）。四道闸全绿，pytest **496/17**（487+9 增量数学吻合）；9/9 O18 测试 PASS；L 本次零偏差（§5 破例）。**D 可续跑 VM 真收口全套**。
- ✅ **GET /api/llm/health 健康检查端点已合**（e2bd033）：4 文件 +226/-0；L 域 `routers/llm.py` + schemas + 测试。**绝不发 httpx POST**（spy `RealLLMClient.__init__` 断言 `init_called==0` 实测过），**绝不回显 api_key**（S9 双重断言子串都不在 response 实测过）。四道闸全绿，pytest **501/17**（496+5 增量数学吻合）；5/5 health 测试 PASS；L 本次零偏差（§5 第四次破例）。复用既有 `real_client.health_check()` 方法挂路由即可。**L 域阶段5 收尾三件套全部到位**。
