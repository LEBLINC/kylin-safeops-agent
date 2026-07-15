# Kylin SafeOps Agent — 项目整体进度快照（给 D / X）

> 维护：L（集成 + 审阅窗口）。基线：**dev = `ccccf5c`（origin 已同步）**。日期：2026-06-22。
> 用途：让 D / X 看清当前整条线在哪、自己下一步做什么。详细决策见 `集成对齐备忘.md`。
> ★本快照自 dev=`cc4b527` 起为**当前权威**；§4 决策记录是历史沉淀（按编号勿翻案）；§2 旧版"已入库内容"按时间倒序补到 §6。

---

## 0. 一句话状态

**「阶段6 全部收口」**（dev=`ccccf5c`，2026-06-22）。对外口径：**判定+执行+审计+审批认证+沙箱+反代签名认证+真 LLM+S3 校验+注入红队+间接注入防护+真 LDAP 20组 VM 实证**在麒麟 V11 实机 LoongArch 全链闭合（ADR-0001/0002/0003/0004 均 Accepted）。**三方无待办**。

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

### D — ✅ 阶段6 D 域全收口
- ✅ 真 LDAP VM 实证（slapd + 20 组，d589084）
- ✅ T4 log.compress_rotate keep 死字段清除（ccccf5c）
- **无待办**

### X — ✅ 阶段6 X 域全收口
- ✅ B1/B2 + vitest + P1 LDAP + P2 SSE heartbeat（200a63c）
- ✅ P3 SettingsView LLM健康卡 + ChatView 三栏交互（6f7d34a）
- **无待办**

### L（我）— ✅ 阶段6 L 域全收口
- ✅ T13 get_llm() docstring（3789109）
- ✅ T14 full DN归一化测试 + Python 3.9 compat（c4c555e）
- **无待办**

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

最后更新：dev=`ccccf5c`（2026-06-22，阶段6全收口）。**三方无待办。**
- ✅ **T13 get_llm() docstring**（3789109）
- ✅ **D VM 真 LDAP 实证 20组 PASS + 实证报告**（d589084）：slapd + init.ldif + runbook；verify_chain.valid 全 true；RBAC 矩阵字节级符合 _APPROVABLE
- ✅ **T14 full DN 归一化测试 + Python 3.9 compat**（c4c555e）：`test_real_get_user_memberOf_full_dn_normalized` 覆盖完整DN→role 路径；`from __future__ import annotations` 修 3.9 import 崩溃
- ✅ **P3 SettingsView LLM健康卡 + ChatView 交互优化**（6f7d34a）：前端消费 `/api/llm/health` 7字段接口对齐；S9守住
- ✅ **T4 log.compress_rotate keep 死字段清除**（ccccf5c）：从 `tools_log.py` input_schema + 5处测试引用全部移除
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
- ✅ **★ L #1 probe + T5-T9 + DN 归一化合入**（3b1f47a）：probe `/api/llm/health?probe=true` S9 全守；T5 审计补；T6 离线 wheel；T7 NOTICE；T9 守卫；T10 正则；**P1b DN 归一化**（阻断 D 工单阻断 2）。pytest 512/17（504+8，L 报 519 虚高）；D 工单可上 VM。
- ✅ **★ X P4 合入**（d60e4a7）：SSE done 截胡修复（chat.ts:706 删 stopAssistantTyping，1 行）+ DemoView/ToolsView 风险等级卡片配色统一（R0/R1/R2/R3 4 档）。3 commit fast-forward，C3 严守（frontend-only），pytest 512/17 零回归。L 域 4 Router 工单已落盘 `.claude/l_4_router_workorder.md`（approvals/audit/policy/demo 15 endpoint）。
- ✅ **★ L 域 4 Router 实施完成**（feat/l-4-router-completion @ `990012e`，未合 dev 待审）：6 commit（5 主 + 1 style ruff-format 收口），17 文件 +1473/-3。`/api/approvals` 5 接口（list/d...1024-32 既不阅总式，走byte-种范化）+ EventType 加 `natural_language` + 间接注入防御纵深 `detect_tool_output_injection` 验证。4 用例 + 3 dual fixt...
- ✅ **★ L 域 verified 后 LLM 自然语言总结工单完成**（feat/l-verified-natural-language @ `c4c86dc`，未合 dev 待审）：3 commit（db75ca0 stream+orch / c4c86dc llm+test / HEAD docs+test），8 文件 +485/-8。`natural_language` 事件类型 + 决策⑫ 间接注入防御纵深 `detect_tool_output_injection` + `LLMAdapter.summarize` + `RealLLMClient.summarize`（httpx POST `KYLIN_LLM_SUMMARIZE_TIMEOUT=5s`）+ S9 浅过滤 `_sanitize_for_summary`（6 类 api_key/authorization/bind_password/secret/token/password → `***REDACTED***`）。S3 不破（natural_language 不进 audit 哈希链）/ S8 不杀状态机（summarize 超时不阻断 FINISHED）/ 决策⑫扩展接口已实现。4 个新用例（T1 fake 固定 / T2 timeout 不阻断 / T3 inject 拦下 / T4 S9 spy REDACTED）全 PASS，pytest **534/17**（基线 530 + 4 数学吻合 ✅），四道闸全绿。C3 严守（仅 backend/app + backend/tests + 4 文档），决策①-⑬ / ADR-0001-0004 全守。**§5 红线首条违反已留痕**：commit 1/2 首签 Claude 已 filter-branch 改写为 LEBLINC<L 邮箱>，新 hash `db75ca0` / `c4c86dc`（原 `03f9cad` / `f1f063c`）。
- ✅ **★ X A7 SSE Content-Type charset 修复**（ed3ef82）：`backend/app/api/routers/chat.py:118` `media_type="text/event-stream; charset=utf-8"`（防浏览器 fallback Latin-1 解中文乱码）。`backend/tests/test_sse_charset.py` 3 用例（content-type 头 / UTF-8 字节流 / 源码静态防回归）全 PASS。pytest **537/17**（534 + 3 数学吻合 ✅），四道闸全绿（CI 两次 reformat 已 amend 修齐）。force push 用 `--force-with-lease` 安全模式（origin `154f767..ed3ef82`）。
- ✅ **★ L 域 ?probe=true 审计化 + SSE audit_appended 推送**（febd7e5）：probe 失败走 SqliteAuditSink + SSE channel `probe-watch` 推 `audit_appended` 事件 + 新端点 `/api/llm/health/events`（X 域 P1 订阅入口）。4 用例（T1 failed 写审计 + curr_hash + S9 / T2 SSE audit_appended / T3 timeout / T4 fixture noop）全 PASS，pytest **557/17**（基线 553 + 4 数学吻合 ✅），四道闸全绿。C3 严守（仅 backend/app + backend/tests）。
- 📋 **架构审计+整改工单核验后真实未合 L backlog（6 批 18 commit 待起）**（2026-07-13 之三十八）：B1 Blocker 审计 durability 3 commit + B2 授权层 4 commit + B3 LLM Adapter 2 commit + B4 韧性 + 可观测 2 commit + B5 CI + 灰度 Medium 4 commit + B6 注入共谋 + 降级 3 commit。详见 `.claude/l_backlog_6_batches.md`（架构者留底）。
- ✅ **★ L 域 ?probe=true 审计化 + SSE audit_appended 推送**（feat/l-probe-audit @ `b9e8d06`，未合 dev 待审）：2 commit（da8072a feat+ b9e8d06 test+docs），3 文件 +431/-12。`RealLLMClient.probe(audit_sink=...)` 失败/超时落 SqliteAuditSink（phase=probe_failed + compute_curr_hash 续接 GENESIS）+ emit SSE `audit_appended` 事件到固定 channel `probe-watch`。`/api/llm/health/events` 新 SSE 端点（charset=utf-8）。S8 兜底（audit append 失败 / SSE emit 失败 → logger.warning 不杀 probe 响应）。S9 守门（payload 仅 probe_status/error_detail/latency_ms/model/base_url/ts，不含 api_key/response body）。4 新用例（T1 failed 写审计+curr_hash+S9 / T2 SSE audit_appended / T3 timeout 走审计 / T4 fixture 模式 noop）全 PASS，pytest **557/17**（基线 553 + 4 数学吻合 ✅），四道闸全绿。C3 严守（仅 backend/app + backend/tests）。
- ✅ **★ L 域 X 接入联调 5 接口 + D2 §5 红线守门工单完成**（feat/l-x-integration-5-apis @ `b84b55d`，未合 dev 待审）：4 commit（718074f rca / 82c71d7 overview / fd3807b tools / b84b55d D2 守门），10 文件 +1002/-18。`/api/rca/analyze` 接 evidence list[dict] + 响应 evidence_count；`/api/system/overview` 真填 services / tool_calls_today / denied_today；新增 `/api/system/overview/history?hours=1..168`（series 空待 overview_probe 落库）+ `/api/system/stats?hours=1..168`（by_tool / by_risk / by_status 三维度聚合）；新增 `/api/tools/calls/{call_id}`（末条 EXECUTING/EXECUTED 派生 + S9 args REDACTED）。D2 守门 3 用例钉死 Chat 永远走 fixture（ADR-0003 demo-only）：spy `RealLLMClient.__init__` 计数 == 0 / class 模块名不含 `real_client` / spy `RealLLMClient.completion_fn` 计数 == 0。16 个新用例（3+6+4+3）全 PASS，pytest **553/17**（537 + 16 数学吻合 ✅），四道闸全绿。C3 严守（仅 backend/app + backend/tests + 4 文档），决策⑨⑬⑭ / ADR-0001-0004 / S1-S9 全守。
- ✅ **★ L 域 ?probe=true 审计化 + SSE audit_appended 工单完成**（feat/l-probe-audit @ `721d452`，未合 dev 待审）：2 commit（`da8072a` llm+api / `721d452` test）。`real_client.py probe()` 增 `audit_sink` 参数，失败/超时写 AuditRecord(phase=probe_failed, trace_id=probe-{epoch_ms}, payload=model/base_url/probe_status/latency_ms/error_detail)；`routers/llm.py` 在 audit 落库后反查 curr_hash 经 EventBus emit SSE audit_appended 到固定 channel `probe-watch`；新增 `/api/llm/health/events` SSE 订阅端点。S8 不杀 probe 响应（SSE 兜底只 log warn）；S9 api_key 不进 payload；fixture 模式 audit_trace_id=None 不写审计（噪音最小）。4 新用例（T1 failed 写审计 / T2 SSE audit_appended / T3 timeout 走审计 / T4 fixture noop）全 PASS，pytest **557/17**（553 + 4 数学吻合 ✅），四道闸全绿。C3 严守（仅 backend/app + backend/tests + 4 文档），决策①-⑬ / ADR-0001-0004 全守。
- ✅ **★ L 域审计库 durability Blocker 工单完成**（feat/l-b1-audit-durability @ `a1912ee`，未合 dev 待审）：2 commit（5925a77 L-B4-3 + a1912ee L-B4-2）。**L-B4-3**：SqliteAuditSink __init__ 加 PRAGMA synchronous=FULL + busy_timeout=5000 + flush() + close() 顺序保证；**L-B4-2**：lifespan shutdown 改顺序 drain：registry drain tasks（asyncio.wait_for 2s + cancel）→ bus.drain_all() → audit.flush() → audit.close()。**L-B4-1（commit 2 跳过）**：audit.append 异步化 to_thread 方案在 Windows 触发 sqlite3 + threading + ThreadPoolExecutor 组合的 access violation（Python 3.11 + sqlite3 + check_same_thread=False），需 P2 调研；真生产环境 Linux 主线程 fsync 5-50ms 仍可接受，未做改动。S3 哈希链不动（compute_curr_hash / canonical_json 复用）；S8 fail-closed（flush 失败仅 log）；S9 audit payload 不含敏感字段。9 新用例（4 durability T1-T4 + 5 drain T1-T5）全 PASS，pytest **566/17**（基线 557 + 9 数学吻合 ✅），四道闸全绿。C3 严守（仅 backend/app + backend/tests + 4 文档），决策①-⑬ / ADR-0001-0004 全守。

- ✅ **★ L 域授权层 Blocker 工单部分完成**（feat/l-b2-auth-layer @ `fa1184d`，未合 dev 待审）：2 commit（`d6402a1` L-H1 + `fa1184d` L-H2 helper）。**L-H1 IDOR 修复**：session_store.create(*, owner) + assert_owner() + sessions 5 端点 + chat session_id owner 校验 + principal_for_idor 依赖；修 8 个老测试。**L-H2 require_role helper**：rbac.py 增 require_role + roles_satisfy；router 接线未做（避免破坏 dev 模式测试）。**L-M3 审计链 actor + L-M4 router 接线 + 10 个守门测试** 全部留 P2 backlog（复杂改造）。pytest **566/17** 实跑（基线维持），四道闸全绿。C3 严守（仅 backend/app + backend/tests + 4 文档），决策①-⑬ / ADR-0001-0004 / S3 / S8 / S9 全守。



- ✅ **★ L 域 B2 偏差 5 项补完工单**（feat/l-b2-deviations @ `03e1af9`，未合 dev 待审）：5 commit（`f4cdeb3` SoD check / `6ac4208` test_b2 10 守门 / `a22f7d6` env fallback / `03e1af9` proxy 严测 fixture / `3d341d4` 评审窗口 cherry-pick）。**...10 test_b2 + 2 audit proxy）**。四道闸全绿。C3 严守：仅 backend/app + backend/tests + 4 文档，决策⑬/⑨/⑫ / ADR-0001-0004 不动。


- ✅ **★ L 域 B2 偏差 5 项补完工单完成**（feat/l-b2-deviations @ `03e1af9`，未合 dev 待审）：5 commit（`f4cdeb3` SoD check / `6ac4208` test_b2 10 守门 / `a22f7d6` ...er 5 项偏差 4 项落 + 偏差 5 commit 顺序正确）。pytest **578/17**（基线 566 + 12 = 578 数学吻合 ✅）。四道闸全绿。C3 严守（仅 backend/app + backend/tests + 4 文档），决策①-⑬ / ADR-0001-0004 / S3 / S8 / S9 全守。


---

## ★最新权威状态（dev=`1daf3d4`，2026-07-14 补留底 之四十二-之五十一）

> 修正 §5 红线缺口：B2 之四十一之后 7 个空号 + 后续工单 4 文档留底补完。

- 之四十二 = B3 LLM Adapter safety 收口（919ca42 L-H9 summarize guard / 97482d8 completion_fn / 6bdf9bf schema retry + decision12）
- 之四十三 = ADR-0005 demo-record-mode（56791c0 / 67d1122 / b2eedde / dev ac00aa7）
- 之四十四 = X 4 Router 真接口 + probe SSE（3a11339 / fdaf54f / dev 54d2e7b）
- 之四十五 = B4 EventBus + logging + /health（26fb5c3 / 1a54173 / 8193923 / dev 1c457c3）
- 之四十六 = D bug probe-watch SSE fix（da8072a 合于 B4 P2 期，dev ec8079a）
- 之四十七 = B4 P2 SSE QueueFull 兜底（4cbfa82 / dev 53ace24）
- 之四十八 = B6 + B5 P3 收口（0f20b37 L-C5 / 117de7a L-C6 / a636974 L-M1 / 2d61c8e ASGI chunked / 1ba4cf9 handler 单元守门 / dev 124993a）
- 之四十九 = 阶段5 step 2 真接 LLM + ADR-0006（66f75dd 5.1 fake planner / 46e163e 5.2 S3 schema / 694156a 5.3 rate / 6411a47 5.4 decision12 / c199882 5.5 ADR-0006 / dev 5091a90）
- 之五十 = X byte-verify REJECTED（T1+T2 PASSED 后端 CLEAN / 真根因前端 fallback / dev 1daf3d4）
- 之五十一 = A1 SSO 反代替换 ⏳（HMAC 加 method/path/body/nonce + nonce LRU + 真接 LDAP 部署文档）

---

- 之五十一 = A1 SSO 反代替换 ⏳

---

## ★最新权威状态（dev=`d4ec90d`，2026-07-14 路线图 留底 之五十三）

### 阶段5 P4 收口工单(执行中)

- 5.3 P4：rate-limit/token-cap audit phase 区分
- 5.4 P4：间接注入 decision⑫ end-to-end mock
- 分支：feat/l-stage5-p4-rate-indirect
- pytest 预期：639/17

---

---

## ★最新权威状态（dev=`8944a62`，2026-07-14 A1 SSO 反代替换 之五十二）

A1 收口，5.3/5.4 P4 + L 增量守门 commit 1.5 + 阶段6 启动顺序：
1. A1 SSO 反代替换（之五十二）✅
2. 5.3/5.4 P4 收口（之五十三）
3. L 增量守门 commit 1.5（之五十四）
4. A2 .bat / wsproxy 真接 LDAP
5. B1 audit retention 90d + 100MB 归档
...

---

## ★最新权威状态（dev=`2207366`，2026-07-14 补留底 之五十三/五十四/五十五 完成实录）

> 修正：架构者工单书面预留号"之四十五/四十六/四十七"过期，与文档已有 之四十五-之五十三 冲突。
> 补全下述 3 号完成实录（之五十三/五十四 此前占位未落地，之五十五 从未留痕）。

- **之五十三 ✅** 阶段5 P4 收口：5.3 rate_limited/token_cap phase 区分（`90fdce2`）+ 5.4 间接注入决策⑫ e2e mock T12-T15（`61fb552`）
- **之五十四 ✅** L 增量守门 commit 1.5：byte-verify X REJECTED 修复 + 4 文档留痕守卫脚本（`0a0f69c`）
- **之五十五 ✅** D 阻断 deps v2（`d3a4da7`）+ X P5 summary_fn 真接（`bfcb4e6`）+ X P6 RCA LLM 决策⑫（`e8594a7`）

pytest 亲跑复核：656 passed, 17 skipped（dev `2207366`）。下一批新工作留痕号顺延 之五十六起。

## ★最新权威状态（分支 feat/l-a1-p4-redis-nonce，2026-07-14 之五十六 完成实录）

- **之五十六 ✅** A1 P4 Redis nonce store：NonceStore Protocol + InMemoryNonceStore（`4abc627`，T1-T2）+ RedisNonceStore SETEX/EXISTS fail-soft（`c2fa97d`，T3-T5）

pytest 亲跑复核：661 passed, 17 skipped（分支独立基线 658 + 3 增量）。
## ★最新权威状态（分支 `feat/l-a2-wsproxy-startbat`，2026-07-14 之五十七 A2 wsproxy+start.bat 收口）

- **之五十七 ✅** A2 wsproxy.py 真接 LDAP（`8a71d16`）+ start.bat Windows 启动脚本 + 部署文档补完（`b2db94a`）
- 返修：`deploy/sso/REPLY_DEPLOYMENT.md` §2 字段名纠正（对齐 `ldap_client.py::_REQUIRED_REAL_ENV`）
- pytest 亲跑：659/17（本分支基线 658 + 1 增量 T8）

---

## ★最新权威状态（分支 `feat/l-v2-sign-fix-whoami-idor`，2026-07-15 之五十八 v2 签名收尾）

- **之五十八 ✅** v2 签名收尾 2 bug 修复（D 反馈 P1 实证抓到）：
  - Bug1 whoami 恒 401（v1/v2 签名不匹配）+ 顺带修复 nonce 二次消费自锁风险
  - Bug2 principal_for_idor.roles 恒空（IDOR is_admin 恒 False，审计 actor.roles 全空）
- pytest 亲跑：666/17（dev 基线 664 + 2 增量 T1/T2）

---

## ★最新权威状态（分支 `feat/l-b1-b2-frontdoor-wiring`，2026-07-15 之五十九 B1+B2 前门接线）

> 阶段6 唯一卡启动 Blocker：A1(HMAC v2)+A2(wsproxy 真接 LDAP) 已备齐密码学/LDAP 件，
> 本工单把它们接成生产拓扑（nginx→proxy sidecar→app，非直连绕过）。

- **之五十九**（4 commit）：
  - `11fa54f` B2：`deploy/proxy/proxy.py` 模块 import 期 fail-fast（ADR-0004 第四道保险，落在真跑
    LdapClient 的进程）；`KYLIN_PROXY_ALLOW_MOCK=true` 显式 opt-out 供联调/CI；3 用例 T1-T3
  - `7bea8bf` B1a：新建 `deploy/proxy/kylin-proxy.service`（端口 8080、非 root、EnvironmentFile
    带外注入密钥）；3 用例 T9-T11
  - `78e9589` B1b：`deploy/nginx.conf` 加固——443/TLS + upstream 改指向 sidecar:8080（非直连 app
    的 8000）+ 剥离客户端伪造 X-Auth-*（纵深防御）+ 安全头（HSTS/X-Frame-Options/CSP 等）+
    `limit_req` 限流；5 用例 T12-T16
  - `de64c10` B1c：`deploy/install.sh` 装双单元（app+proxy sidecar）+ 建非 root 系统用户（幂等）+
    生成 `/etc/kylin/proxy.env` 0600 骨架（占位值，不写真密钥）；3 用例 T17-T19
- pytest 亲跑：680/17（分支独立基线 669 + 11 增量数学吻合）
- C3 严守：仅 `deploy/proxy/` + `deploy/nginx.conf` + `deploy/install.sh` + `deploy/proxy/tests/`；
  未碰 `backend/app`（除 proxy.py 一处 fail-fast，非 backend 域）/前端/D 域 sandbox

---
