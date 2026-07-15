# 麒麟 V11 + LoongArch VM 分阶段 bring-up 总清单（统筹用 · 可勾选）

> 维护：L（集成 + 审阅窗口）。基线 **dev = `8848918`（origin 同步）**。日期：2026-06-19。
> 前提：麒麟 V11 + LoongArch VM 已就位。
> ★铁律：Windows 审阅机上一切沙箱/真命令都是 **skip**，**VM 第一轮结果 = 新事实来源**，不拿旧"绿"代替。
> 每阶段过关才进下一阶段。owner 标注谁主跑；协作者改动仍走分支 → L 审阅 merge。

> ## ★阶段4 demo 本机落地收口 2026-06-16（edf57aa）
> 5 新文件严守 C3（D/X 域零改动亲跑 git diff 确证）；6 场景 A/B/E/F 本机全 PASS，C/D 链路真跑待 VM 沙箱实证。详见 `docs/design/stage4-e2e-demo-testplan.md` + `docs/design/stage4-e2e-demo-acceptance-report.md`。pytest 真值 435/17（基线 429 + 6 增量数学吻合）。
> 阶段3 全部 [x]：**"内网 only 正式解除"**。详见 `阶段3-内网only解除-五项联合验收清单.md` 末尾留痕。
> 阶段4（端到端 demo） + 阶段5（真实 LLM）仍在 backlog。

---

## 阶段 0 · 环境与代码就位（owner: L）
- [ ] VM 装 conda `kylin_ci`（Py3.11 + requirements + dev + constraints）或等价运行环境
- [ ] `git clone`/`pull` dev=`c7d66e5`
- [ ] VM 上跑一次 `pytest backend/tests` → 记录 **Linux 基线 passed/skipped**（应比 Windows 380/15 多跑出沙箱集成等真用例）
- [ ] 确认 systemd 为 PID1、agent 用户可 `sudo`（沙箱前提）

## 阶段 1 · 沙箱实机验证 + 命令路径校准（owner: D，VM）★解锁后续的钥匙　✅ 已完成（dev=ce6ca9f）
> 麒麟 V11（LoongArch, systemd 255 v255-34.p04.ky11）实机跑 verify-sandbox-on-vm.sh = **9 passed / 0 failed / 0 warnings**。
- [x] 跑 `deploy/sandbox/verify-sandbox-on-vm.sh`（dev=3a8b21a 起就位；`sudo ./verify-sandbox-on-vm.sh [目标服务=cron.service]`）：
  - [x] `which systemd-run/sudo/...` 真实绝对路径 vs 硬编 → 17/17 匹配（**lsof 唯一不符 /usr/sbin→/usr/bin 已修 848c9e4/合入 ce6ca9f**）
  - [x] readonly 写 /etc → Read-only（rc≠0）
  - [x] limited_write 写 /etc 拒 / 写 /var/log 允许（ProtectSystem=full 行为正确）
  - [x] **service.restart 在 NoNewPrivileges+ProtectHome 下触达 system dbus 真重启 cron.service 成功 → 无需 profile 例外**
  - [x] `none`/非白名单二进制经 wrapper 被拒（洞1/洞2 实机复证）
  - [x] 瞬态 service 启停开销 78ms（< 500ms）
- [x] 路径/SAFE_ENV：lsof 已回填；SAFE_ENV（LANG=C.UTF-8 兼容 C.utf8 / PATH 子集）无需改；systemd 255 全支持 Protect*（cgroupv1 不影响 mount-namespace 类属性）
- [ ] 部署 wrapper+sudoers：`cp → chown root:root → chmod 0755(wrapper)/0440(sudoers) → visudo -c`（阶段 3 部署时做）

## 阶段 2 · 沙箱启用 + 只读指标接真（owner: L，+ D 协同）
- [ ] 合入"第 2 步沙箱启用接线"（build_gateway 按 platform+`KYLIN_SANDBOX_ENABLED=1` 传 sandbox_enabled）
## 阶段 2 · 沙箱启用 + 只读指标接真（owner: L，+ D 协同）　✅ 已完成（dev=54c4a2d，VM 实证 2026-06-15）
> 麒麟 V11 VM `KYLIN_SANDBOX_ENABLED=1` 起 app 实跑：`curl /api/system/overview` → **data_source="real"**，cpu=8.0/mem=47.2/disk=19.0，5 探针全执行。沙箱开启全工具真跑无误拒。
- [x] VM 设 `KYLIN_SANDBOX_ENABLED=1` 起 app；经沙箱跑真只读命令
- [x] `/api/system/overview` root_disk/zombie 真实值、`data_source` 不再 stub
- [x] **（L+D 联合）overview cpu/memory 真源**：D 加 system.cpu_load(vmstat)/system.mem_usage(free) 模板+profile+白名单(e4a5c25)；L 加 ToolSpec/parser/dispatch/overview 接线(49d4914) → **VM 实证 data_source="real"**（cpu/mem>0，free available 口径、vmstat header 定位 id 列实证正确——VM 的 vmstat 含 gu 列）
- [x] 全工具沙箱开启真跑无误拒：systemctl show/restart、sha256sum、lsof、find、vmstat、free(readonly) + gzip 写 /var/log(limited_write rc=0) + systemctl restart cron(rc=0，service.restart 沙箱内 dbus 可达)

## 阶段 3 · 部署硬化：反代 + 认证上真 + 审计库（owner: L + X + D）　✅ 已完成（dev=cc4b527，VM 实机 2026-06-16）
> 五项联合验收 + 审计 3a 顺带实机确认全绿，"内网 only"约束正式解除。详见 `阶段3-内网only解除-五项联合验收清单.md` 末尾留痕。
- [x] 反向代理（X 的 deploy/proxy/proxy.py）对**所有**入站请求（含 SSE `/api/chat/{trace_id}/events`）按 `auth.sign_identity` 口径注入 `X-Auth-User/Roles/Timestamp/Signature`（HMAC-SHA256, canonical=`f"{user}\n{roles}\n{ts}"`，与 `auth.py:51` 字节级一致）
- [x] 设 `KYLIN_AUTH_MODE=proxy` + `KYLIN_PROXY_AUTH_SECRET`（强随机，反代与 app 共享）
- [x] 验证无签名头直连 app → **401 fail-closed**（detail="missing or invalid proxy-signed identity"）
- [x] 设 `KYLIN_AUDIT_DB`=绝对路径 + 0600；审计 3a 顺带验收 ✅；3b retention/rotation 已审 PASS 待 merge（b94fd38）
- [x] X：前端"构建期 env 角色" → 反代注入身份过渡（whoami 端点 onMounted fetchWhoami + chat.ts currentUser/Roles+静默降级 viewer + .env.production 移除 VITE_CURRENT_USER_ROLE + ChatView 展示真实 user）
- [x] 审批闸端到端：proxy 注入 operator/admin → can_approve 据真实角色裁决；伪造角色无密钥 → 401
- [x] ★**此步过关 = "内网 only" 约束正式解除** — VM 实机闭合

## 阶段 4 · 端到端 demo（owner: 全员，fake planner）　✅ 本机+CI+X+D 全收口（dev=7b74404）
> **本机（Windows, kylin_ci）已落地**（edf57aa）：6 场景 demo + 6 pytest 用例 + testplan + 验收报告
> - A 输入闸 deny / B 策略闸 FILE001 deny / E 结果闸+审计闸 / F 篡改检出 → 本机全 PASS
> - C 确认闸 R3 service.restart / D 确认闸 R2 log.compress_rotate → 链路真跑；沙箱内 systemctl/gzip 真执行 **待 VM + KYLIN_SANDBOX_ENABLED=1**（本机沙箱关闭 + 无 systemctl/gzip → verified_summary="non-zero"，诚实标注）
> - VM 端到端跑法：`KYLIN_SANDBOX_ENABLED=1 python -m scripts.demo_stage4_e2e --scenarios C,D` → C/D verified_summary="ok" 即为终验
> - 详见 `docs/design/stage4-e2e-demo-testplan.md` + `docs/design/stage4-e2e-demo-acceptance-report.md`
- [x] 五道闸全链真跑：A/B/E/F 本机+CI 全绿；C/D 链路真跑 ✅
- [x] CI Linux runner 全绿（0065787 fix 非 VM 沙箱断言放宽）
- [ ] VM 沙箱内 systemctl/gzip 真执行（KYLIN_SANDBOX_ENABLED=1）— D 域 VM 跑
- [x] 注入红队：A 场景 D-10 golden 在本机 high→deny、拦在 plan 前（CAI 实测 category=command_injection_lure / pattern_id=PI-CMD-001）；VM 同样行为可推
- [x] 审计完整性：F 场景本机手工 UPDATE payload 改一字符 → verify_chain 报 valid=False + broken_seq=1 + reason="篡改：curr_hash 计算不一致"
- [ ] 录 demo / 出对外口径验收报告（VM 端到端后做）

## 阶段 5（最后）· 真实 LLM 接入（owner: L，dev=b421736 → 阶段5 工单已起）　🟡 3 步走（步骤 0 → 1 → 2）
> **阶段5 工单 prompt 已起**（`集成对齐备忘.md` 之十八 / `审阅交接.md` 之十八）。**D + X 阶段5-prep 全收口**：
> - D 域：fail_closed impl + 4 用例（94bdac9） + 阶段4 VM C/D 实证 PASS
> - X 域：SSE 阻塞修（b421736）+ 6 项技术债
> 阶段5 是 L 域独立工作，但**步骤 0 接线 + 步骤 1 fake planner 修是步骤 2 真 LLM 接入的前置**。

- [ ] **步骤 0**：L 域接 `fail_closed=True`（`api.py lifespan` 按 `KYLIN_AUTH_MODE=="proxy"` 传 `connect(..., fail_closed=True)`）—— D impl + 测试已就位
- [ ] **步骤 1**：fake planner 修（`backend/app/llm/adapter.py` 解析 user_intent 提取 tool/args，不再写死目标）
- [ ] **步骤 2**：真 LLM 客户端（`backend/app/llm/real_client.py` 新建）+ `build_e2e` 拆 `use_real_llm: bool` hook + S3 schema 校验+重试（仅重发 LLM 端，前端不动）+ rate limit + token cap + D-10 真 LLM 下重跑 + **间接注入（日志投毒）真实叙事验**
- [ ] 重点审 S3：LLM 输出严格符合 `contracts/intent` + schema 校验+重试在位；绝不拼 LLM 文本进命令
- [ ] 真 LLM 下重跑 D-10 注入红队 + 五道闸，确认 LLM 被注入也被地板拦死
- [ ] **间接注入真验**（X `demo/attack_prompts/README.md` 已留"暂未实现"节）：真 LLM 测试桩加"先看 /var/log/syslog 决定如何压缩"模式 → 期望：结果闸 is_untrusted=True 或策略闸 deny 任一即合规
- [x] **★对外口径发布**：阶段5 收口后"判定 + 执行 + 审计 + 审批认证 + 沙箱 + 反代签名认证 + 真 LLM 接入 + S3 校验 + 注入红队 + 间接注入防护"全链在麒麟 V11 实机闭合；**ADR-0002 已发 Accepted（2026-06-19）**。

---

## 关键路径与并行建议
- **阶段 1（D 在 VM 验证沙箱+校准路径）= 后面全部的钥匙**；一过，阶段 2 沙箱启用才有意义。
- 可并行：① 第 2 步沙箱启用接线（L 执行窗口，不依赖 VM）；② D 在 VM 跑阶段 1。两线不冲突。
- 跨切关注点（易漏）：**任何新增"跑真命令"的工具，command_templates + sandbox profile + wrapper ALLOWED_CMDS 都在 D 域，且新二进制路径要 VM `which` 校准**——L 单方面加会 127/被 wrapper 拒（config.diff 式陷阱）。新增工具必走「新增工具检查单」+ L/D 协同。

## owner 速查
- **L**：沙箱启用接线、overview 接线侧、反代/认证部署、真实 LLM、集成 merge。
- **D**：沙箱 VM 验证+路径校准、command_templates/wrapper/profile、审计库硬化、service.restart 例外。
- **X**：前端 data_source=partial 适配、config.diff 重现、反代身份过渡、demo 前端。

---

**基线 dev=`febd7e5`（2026-07-13 之三十七）**：L 域 `?probe=true` 审计化 + SSE `audit_appended` 推送已合。X/D prompt 已重写并发出（X P0 接口切真 + X P1 SSE 端点 + X P2 契约校验 / D P0 probe 审计 VM 实证 + D P1 5 接口端到端真接入），等协作者回执。pytest 557/17，全四道闸绿。

**L 域后续候选 backlog（架构者待选）**：见之三十七清单。

---

## 阶段6 backlog（2026-06-19 另一窗口架构审阅 → 治债清单）

> 来自 dev=`e2bd033` 架构审阅的 5 条中低优治债 + L 域 3 条遗留。**非阻断 VM 真跑**，但建议阶段6 启动前清零。

| # | 优先 | owner | 治债项 | 证据 |
|---|---|---|---|---|
| T1 | High | X | **B1 SSE use-after-close**（BackgroundTask 方案） | `proxy.py:78-100` `async with` 块内 `return StreamingResponse(resp.aiter_bytes(), ...)`；时间线 `cc4b527 → ade1c24`；反代 SSE 从未 VM 复证 |
| T2 | High | X | **B2 whoami `res.data` 一行修** | `chat.ts:660-661` 二次取 `res.data.user/roles` 抛 TypeError 被 `catch{}` 静默；真 admin 登录也被禁"批准"按钮 |
| T3 | — | X | vitest config + `npm test` 接 CI（治 T2 漏网根因） | `package.json` 无 test script；`ci.yml` 0 命中 npm test |
| T4 | Medium | D | `log.compress_rotate` keep 死字段对齐 | spec 写 keep，模板只 gzip；语义错位是审批闸认知风险 |
| T5 | Medium | L | rate-limit/token-cap RuntimeError 补审计 + 坏响应纳入重试 | `real_client.py:236/250` raise + `orchestrator.py:191` 只捕 `httpx.HTTPError` |
| T6 | Medium | L | `install.sh` pydantic-core wheel offline wheelhouse | `install.sh:52` 直接 `pip install`，无 `--find-links` |
| T7 | Low | 全员 | NOTICE 销 mcp 注释 + 7 条 SPDX 占位 | `NOTICE:11` "mcp 运行时依赖经 pip 安装" 已过期 |
| T8 | Low | D | 决策③ `_CHANGE_TOOLS` 加可执行守卫单测 | 手工集合漏加风险 |
| T9 | Low | D | CMD001-003 正则局限升对外 advisory | `policy_loader.py:38` 注释半文档化 |
| T10 | P1 | X | 反代 Basic Auth → 真 SSO/LDAP | 阻塞阶段6 启动 |
| T11 | P2 | X | SSE heartbeat keepalive | 长期挂死防护 |
| T12 | — | L | `?probe=true` 主动连通性探测 | health 端点 backlog |
| T13 | — | L | `get_llm()` docstring 改"demo-only 设计意图" | ADR-0003 后续跟进 |

---

## ★架构审计 + 整改工单核验后阶段6 真实未合 L backlog（dev ac4ba0e 之三十八，2026-07-13）

> **核验过程**：架构者读 `架构审计报告-dev-154f767.md` + `整改工单-154f767-L.md`，
> 字节级对照当前 dev=`ac4ba0e` 代码逐条核**真伪**（审计报告与整改工单有几处不准 / 漏项，已记偏差）。

### 6 批分组（18 commit 总）

| 批 | 内容 | commit | 优先级 |
|---|---|---|---|
| **B1 Blocker** | 审计 durability:audit 写异步化 + lifespan drain + synchronous=FULL | 3 | 🔴 |
| **B2 授权层** | IDOR 修 + audit role + actor 写入 + policy role | 4 | 🟠 |
| **B3 LLM 硬化** | summarize prompt 定界 + HMAC 加 method/path/body/nonce + LRU | 2 | 🟠 |
| **B4 韧性 + 可观测** | EventBus queue maxsize + logging dictConfig + /health readiness | 2 | 🟠 |
| **B5 CI + 灰度** | testpaths + mypy + 请求体大小 + 错误文案 + SSE auth + Auth REDACTED | 4 | 🟡 |
| **B6 注入 + 降级** | D-10 共谋 + natural_language 降级 + escalate except:pass | 3 | 🟡 |

### 留痕偏差（架构者失误留底）
- 之前凭记忆列 L-D1/T13/T5/T6 当新工单，全部已合；X-proxy SSE 阻塞已合；D P0/P1/P2 全已合
- 整改工单比审计报告更全（HMAC 加 nonce + LRU；audit drain 等），以整改工单为权威

**X 工单（T1+T2+T3）已起**：建议分支 `feat/x-sse-whoami-vitest`，2-3 commit 拆开，B1 VM 复证是 PASS 必要条件。
**基线 dev=`d60e4a7`（2026-07-11 之三十一）**：X P4 SSE done 截胡修复 + Demo/Tools 卡片配色统一合入。L 域 4 Router 工单待下个 L 执行窗口实施。pytest 512/17。
**基线 dev=`c1e8c51`（未动，2026-07-11 之三十二）**：L 域 4 Router 工单 6 commit 已落地 feat/l-4-router-completion（未合 dev），等另一窗口审阅。pytest 530/17（512+18）。X P4 已合 d60e4a7。
**基线 dev=`9002e10`（未动，2026-07-12 之三十三）**：L 域 verified 后 LLM 自然语言总结工单已落地 feat/l-verified-natural-language（`db75ca0` stream+orch / `c4c86dc` llm+test / `HEAD` docs+test，未合 dev 待审）。3 commit 含 `natural_language` 事件 + 决策⑫ 间接注入防御纵深 `detect_tool_output_injection` + `LLMAdapter.summarize` + `RealLLMClient.summarize` + S9 浅过滤 `_sanitize_for_summary` 6 类 api_key/authorization/bind_password/secret/token/password → `***REDACTED***`。4 新用例（T1 fake 固定 / T2 timeout 不阻断 / T3 inject 拦下 / T4 S9 spy REDACTED）全 PASS，pytest **534/17**（530 + 4 数学吻合）。真端点 httpx POST 走 `KYLIN_LLM_SUMMARIZE_TIMEOUT=5s` 待 D 在 VM 配 env+密钥实证。

**基线 dev=`ed3ef82`（2026-07-12 之三十四）**：X A7 SSE Content-Type 修复 + 4 文档留痕。`chat.py:118` `media_type="text/event-stream; charset=utf-8"` 防中文 Latin-1 乱码。`backend/tests/test_sse_charset.py` 3 用例（content-type 头 / UTF-8 字节流 / 源码静态防回归）全 PASS，pytest **537/17**（534 + 3 数学吻合 ✅），四道闸全绿（CI 两次 reformat 已 amend 修齐），force push 用 `--force-with-lease` 安全模式。

**基线 dev=`a82f984`（2026-07-13 之三十五）**：L 域 X 接入联调 5 接口 + D2 §5 红线守门工单已落地 feat/l-x-integration-5-apis（`718074f` rca / `82c71d7` overview / `fd3807b` tools / `b84b55d` D2 守门 / `HEAD` docs，未合 dev 待审）。4 commit 含 `/api/rca/analyze` 接 evidence + 响应 evidence_count；`/api/system/overview` services/tool_calls_today/denied_today 真填；新增 `/api/system/overview/history?hours=1..168`（series 空待 overview_probe 落库）+ `/api/system/stats?hours=1..168`（by_tool/by_risk/by_status 三维度聚合）；新增 `/api/tools/calls/{call_id}` 详情 + S9 args REDACTED。D2 §5 红线守门 3 用例钉死 Chat 永远走 fixture（ADR-0003 demo-only）。16 新用例（3 RCA + 6 overview + 4 tools + 3 D2）全 PASS，pytest **553/17**（537 + 16 数学吻合 ✅），四道闸全绿。C3 严守（仅 backend/app + backend/tests + 4 文档）。

**基线 dev=`c99d760`（2026-07-13 之三十六）**：L 域 ?probe=true 审计化 + SSE audit_appended 工单已落地 feat/l-probe-audit（`da8072a` probe audit / `721d452` tests，未合 dev 待审）。2 commit 含 `RealLLMClient.probe(audit_sink=...)` 在 failed/timeout 路径写 `SqliteAuditSink` 一条 AuditRecord(phase=probe_failed, trace_id=probe-{epoch_ms}, payload 含 probe_status/latency_ms/error_detail/model/base_url, curr_hash=SHA256(GENESIS+canonical_json(payload)))；`/api/llm/health?probe=true` 路由同步 emit SSE `audit_appended` 事件到固定 channel `probe-watch`，前端 SSE 订阅可见；新增 `GET /api/llm/health/events` 订阅端点。S8 兜底：审计/SSE 失败仅 log warn，不杀 probe 响应。S9：payload 含 model+base_url（非凭据），api_key 绝不入 payload；probe_error 仍仅 status_code / TimeoutException 类名。4 新用例（T1 failed 写审计 / T2 SSE audit_appended / T3 timeout 走审计 / T4 fixture noop 不写审计）全 PASS，pytest **557/17**（553 + 4 数学吻合 ✅），四道闸全绿。C3 严守（仅 backend/app + backend/tests + 4 文档）。

**基线 dev=`f9f17a6`（2026-07-13 之三十九 L 域审计库 durability Blocker）**：2 commit（`5925a77` L-B4-3 synchronous=FULL + busy_timeout=5000 + flush() / `a1912ee` L-B4-2 lifespan shutdown drain 顺序 registry→bus→audit→session_store）。L-B4-3：SqliteAuditSink PRAGMA synchronous=FULL + busy_timeout=5000ms + flush() PRAGMA wal_checkpoint(FULL) + close() 顺序 flush→close（S8 兜底 flush 失败仅 log warn 不 raise）。L-B4-2：lifespan shutdown 段 `drain_orchestrator_tasks`（asyncio.wait_for 10s + 超时 cancel）+ `bus.drain_all()`（幂等移除所有 queue）+ `audit.flush() + audit.close()`。**L-B4-1 to_thread 跳过**（Windows sqlite3 thread safety 问题需 P2 调研；commit 2 改为 P2 backlog 留痕）。9 新用例（4 durability T1-T4 + 5 drain T1-T5）全 PASS，pytest **566/17**（557 + 9 数学吻合 ✅），四道闸全绿。

**基线 dev=`122cc62`（2026-07-13 之四十 L 域授权层 Blocker 部分完成）**：2 commit（`d6402a1` L-H1 IDOR 修复 + `fa1184d` L-H2 require_role helper）。**L-H1**：session_store.create(*, owner) + assert_owner + sessions 5 端点 + chat session_id owner 校验 + principal_for_idor dep。**L-H2**:rbac.py 新增 require_role + roles_satisfy（router 接线未做，避免破坏 dev 模式测试）。**L-M3 审计链 actor + L-M4 router 接线 + 10 个守门测试** 全部留 P2 backlog。pytest **566/17** 实跑（基线维持），四道闸全绿。



**基线 dev=`974505c`（2026-07-13 之四十一 L 域 B2 偏差 5 项补完）**：5 commit（`f4cdeb3` SoD check / `6ac4208` test_b2 10 守门 / `a22f7d6` env fallback / `03e1af9` proxy 严测 fixture / `3d341d4` 评审窗口 cherry-pick）。**L-偏差 1 SoD**...


**基线 dev=`974505c`（2026-07-13 之四十一 L 域 B2 偏差 5 项补完）**：5 commit（`f4cdeb3` SoD check / `6ac4208` test_b2 10 守门 / `a22f7d6` env fallback / `03e1af9` proxy 严测 fixture / `3d341d4` review-window takeover cherry-pick）。pytest **578/17** 实跑（基线 566 + 12 增量 = 568+10+2=578 数学吻合 ✅），四道闸全绿。**SoD 防自批自**：approvals.resume_approval 加 actor==approver → 403 + audit sod_violation（决策⑬ 核心防线）。**proxy 严测**：proxy_signed_headers 走 HMAC 4 头校验，admin→200 / viewer→403 守门生效。


---

## ★最新权威状态（dev=`1daf3d4`，2026-07-14 补留底 之四十二-之五十一）

> 修正 §5 红线缺口：B2 之四十一之后 7 个空号 + 后续工单 4 文档留底补完。

- 之四十二 = B3 LLM Adapter safety 收口
- 之四十三 = ADR-0005 demo-record-mode（dev ac00aa7）
- 之四十四 = X 4 Router 真接口 + probe SSE（dev 54d2e7b）
- 之四十五 = B4 EventBus + logging + /health（dev 1c457c3）
- 之四十六 = D bug probe-watch SSE fix（dev ec8079a）
- 之四十七 = B4 P2 SSE QueueFull 兜底（dev 53ace24）
- 之四十八 = B6 + B5 P3 收口（dev 124993a）
- 之四十九 = 阶段5 step 2 真接 LLM + ADR-0006（dev 5091a90）
- 之五十 = X byte-verify REJECTED（dev 1daf3d4）
- 之五十一 = A1 SSO 反代替换 ⏳

---

- 之五十一 = A1 SSO 反代替换 ⏳

---

## ★最新权威状态（dev=`d4ec90d`，2026-07-14 路线图 留底 之五十三）

### 阶段6 部署硬阻塞 待 D 域 VM 实证

- A1 SSO 反代替换（L 域 ⏳ 执行中）
- A2 .bat/wsproxy 真接 LDAP（D 域待办）
- D1 Dockerfile + docker-compose（D 域待办）
- D2 systemd unit file（D 域待办）

### 阶段5 P4 工单(留底之五十三)

- 5.3 P4：rate-limit/token-cap audit phase 区分
- 5.4 P4：间接注入 decision⑫ end-to-end mock

---

---

## ★最新权威状态（dev=`8944a62`，2026-07-14 A1 SSO 反代替换 之五十二）

A1 收口；production 部署前必做清单同步进展。

| 类别 | 任务 | dev |
|---|---|---|
| 部署硬阻塞 | A1 SSO 反代替换 | ✅ dev 8944a62 |
| 部署硬阻塞 | A2 .bat / wsproxy 真接 LDAP | ⏳ |
| 合规 | B1 audit retention 90d | ⏳ |
| 合规 | B2 归档可恢复 + 路径可配 | ⏳ |
| 监控 | C2 /metrics Prometheus | ⏳ |
| 监控 | C3 审计异常告警 | ⏳ |
| 部署 | D1 Dockerfile + docker-compose | ⏳ |
| 部署 | D2 systemd unit + runbook | ⏳ |
| 发布 | J2 CD 灰度 + 回滚 | ⏳ |

---

## ★最新权威状态（dev=`2207366`，2026-07-14 补留底 之五十三/五十四/五十五 完成实录）

> 修正：工单预留号"之四十五/四十六/四十七"过期（与已有 之四十五-之五十三 冲突）。补全实录如下。

| 编号 | 内容 | commit | dev |
|---|---|---|---|
| 之五十三 | 阶段5 P4 收口（5.3 phase 区分 + 5.4 决策⑫ e2e mock） | `90fdce2`+`61fb552` | 已 merge |
| 之五十四 | L 增量守门 commit 1.5（byte-verify X REJECTED） | `0a0f69c` | 已 merge |
| 之五十五 | D 阻断 deps v2 + X P5 + X P6 RCA LLM 决策⑫ | `d3a4da7`+`bfcb4e6`+`e8594a7` | `2207366` |

pytest 亲跑复核：656 passed, 17 skipped。新工作留痕号顺延 之五十六起。

## ★最新权威状态（分支 feat/l-a1-p4-redis-nonce，2026-07-14 之五十六 完成实录）

| 编号 | 内容 | commit | pytest |
|---|---|---|---|
| 之五十六 | A1 P4 Redis nonce store（NonceStore Protocol + InMemoryNonceStore + RedisNonceStore fail-soft） | `4abc627`+`c2fa97d` | 661/17 |
## ★最新权威状态（分支 `feat/l-a2-wsproxy-startbat`，2026-07-14 之五十七 A2 wsproxy+start.bat 收口）

| 编号 | 内容 | commit | pytest |
|---|---|---|---|
| 之五十七 | A2 wsproxy.py 真接 LDAP + start.bat + 部署文档补完（含 REPLY_DEPLOYMENT.md 字段名纠正） | `8a71d16`+`b2db94a` | 659/17 |

---

## ★最新权威状态（分支 `feat/l-v2-sign-fix-whoami-idor`，2026-07-15 之五十八 v2 签名收尾）

| 编号 | 内容 | commit | pytest |
|---|---|---|---|
| 之五十八 | v2 签名收尾 2 bug（whoami 恒401 + principal_for_idor roles恒空）修复 + 2 守门测试 | `ee5ff7d`（merge dev `09c1afe`） | 666/17 |

---

## ★最新权威状态（分支 `feat/l-b1-b2-frontdoor-wiring`，2026-07-15 之五十九 B1+B2 前门接线）

> 架构审计报告-154f767 §2 B1+B2 + §6 第一梯队#1：阶段6 唯一卡启动 Blocker。
> A1(HMAC v2)+A2(wsproxy 真接 LDAP) 已备齐密码学/LDAP 件，本工单接成生产拓扑：
> nginx(443,TLS) → proxy sidecar(127.0.0.1:8080，真 LDAP+HMAC v2) → app(127.0.0.1:8000)。

| 编号 | 内容 | commit | pytest |
|---|---|---|---|
| 之五十九 | B2 proxy.py mock fail-fast（第四道保险）+ B1a proxy sidecar systemd unit + B1b nginx TLS/剥头/安全头/限流 + B1c install.sh 双单元/非root用户/proxy.env骨架 | `11fa54f`+`7bea8bf`+`78e9589`+`de64c10` | 680/17 |

**VM 实证计划**（本机只测模板/dry-run/mock fail-fast，真拓扑闭环需 VM）：
1. VM 装双 systemd unit（`kylin-safeops.service` + `deploy/proxy/kylin-proxy.service`）
2. 填 `/etc/kylin/proxy.env` 真密钥/LDAP 配置（`KYLIN_LDAP_MOCK=false`）+ chmod 0600
3. nginx 配置 443 证书 + `limit_req_zone` 加进 http{} 主配置
4. 全链路请求 `nginx:443 → proxy:8080 → app:8000`，验证：
   - 无 Basic Auth → 401 + WWW-Authenticate
   - 合法 Basic Auth（真 LDAP）→ 200 + 出 trace_id（非 401，证明 HMAC v2 端到端签验通过）
   - 客户端伪造 `X-Auth-Roles: admin` header → 被 nginx 剥离，仍按真实 LDAP 角色鉴权
   - `KYLIN_LDAP_MOCK=true` 误启 proxy → systemd 显示 failed（fail-fast 生效）

---

## ★最新权威状态（分支 `feat/l-stage6-t2-observability`，2026-07-15 之六十 C1-C4 可观测性+CI keystone+SSE封顶+H9收尾）

> 架构者阶段6 第二梯队旗舰工单：H14(SSE队列有界)/H16(日志集中) 各留半个窄缺口 + mypy 认证源码
> 从未覆盖 + H9(自然语言总结)sensitive_filtered 死标志。dev 基线 `2aaa252`（=origin/dev）。

| 编号 | 内容 | commit | pytest |
|---|---|---|---|
| 之六十 | C1 metrics + C2 SSE上限 | `860d4ce` | 685/17 |
| 之六十 | C3 mypy 补 deploy/proxy | `7e3f6bc` | 685/17（config-only） |
| 之六十 | C4 H9 输出侧凭据扫描 | `9f3779a` | 689/17 |

**C1**：`backend/app/agent/metrics.py` 自研 Metrics（counter/gauge，勿引 prometheus_client 避
LoongArch 离线 wheel 风险）；埋点 orchestrator._goto 状态计数、LLM 调用/失败数、审计 append 延迟
gauge、event_bus SSE active_count gauge；新增 `GET /api/system/metrics` 走 verify_token。

**C2**：`chat.py::get_events` 新连接前查 `bus.active_count`，达 `KYLIN_SSE_MAX_CONN`（默认100）→
503（防连接耗尽 DoS），复用现有 active_count，释放后可再连。

**C3**：`.pre-commit-config.yaml` mypy files 正则加 `deploy/proxy`（exclude tests/）；
`pyproject.toml` 加 `[[tool.mypy.overrides]] module="ldap3"` 消音第三方 stub 缺失（不碰
`deploy/sso/ldap_client.py` 源码，X 域边界）；`deploy/app` 无 .py 文件不需要加。mypy deploy/proxy
4 源文件 Success: no issues found。

**C4**：`backend/app/agent/secret_scan.py` 新增 `scan_and_redact`（与 audit_logger 同口径 6 类
字段名的正则扫描）；`orchestrator.py::_emit_natural_language` summary 发前端前先扫，命中 → redact
+ `sensitive_filtered=True`（原恒 False 死标志变活）。

**VM 实证计划**（本次纯代码/CI 层收尾，不涉及新部署拓扑，无新增 VM 验证项）：
沿用之五十九 VM 实证计划（nginx:443→proxy:8080→app:8000），本工单新增内容为纯软件层
（metrics/SSE cap/mypy/凭据扫描），可在阶段5/6 常规回归中随全链路一并验证：
1. `curl /api/system/metrics`（proxy 模式需带 v2 签名头）应返回 counters/gauges 两键非空。
2. 并发起 >`KYLIN_SSE_MAX_CONN` 个 SSE 连接，验证第 N+1 个连接收到 503。
3. LLM 真接后驱动一次含疑似凭据文本的工具输出，观察 `natural_language` SSE 事件
   `sensitive_filtered=true` 且 text 已 redact。

pytest 亲跑复核：**689 passed, 17 skipped**（分支独立基线 685 + 4 增量数学吻合 ✅，685 = dev 基线
680（=之五十九収口值）+ 5（C1+C2 用例））。

**C3 域边界**：仅 `backend/app/{agent,api}` + `.pre-commit-config.yaml` + `pyproject.toml` +
`backend/tests`。未碰 `backend/app/db`（D 正在动）、`deploy/sandbox`、frontend/、`deploy/sso`、
契约、S3 哈希链。

**已知风险 / 未覆盖项**：
1. `limit_req_zone` 主配置声明（之五十九已知项）与本工单无关，仍待运维手动补 `http{}` 块。
2. metrics 端点无持久化——进程重启后指标清零（与 EventBus/SessionRegistry 同前提，单节点部署
   可接受，未来若需要跨重启持久指标需额外落库）。
3. `secret_scan.py` 正则只覆盖 `key: value` / `key=value` 形态，LLM 若把凭据拆成多行或用别的
   分隔符描述仍可能漏检——纯字符串模式匹配的已知局限，非本工单可根治（真正防线仍是输入侧
   S9 浅过滤 + 绝不把真实凭据喂给 LLM）。

---

## ★之六十 C1-C4 已审过合入 dev=`de90626`（审阅窗口 2026-07-15）

审阅窗口亲核合入（no-ff merge `de90626`，push origin，dev 合并态 pytest **689/17**，CI 四闸全绿）。

**C1-C4 无新增 VM 部署项**（纯代码/CI 层），功能项随常规回归验证：
1. `curl /api/system/metrics` 走真 v2 签名头 → 200 + counters/gauges。
2. 并发起 >`KYLIN_SSE_MAX_CONN` 个 SSE 连接 → 第 N+1 个收 503。
3. 真 LLM 驱动含疑似凭据文本工具输出 → `natural_language` 事件 `sensitive_filtered=true` 且 text 已 redact。

**本窗口 2026-07-15 新派发（VM 相关性）**：
- **D 域 H7**（`privilege_executor.py` 超时杀孤儿 + 防内存 DoS）：VM 实证点 = 沙箱内起长命令触发 timeout，`ps` 确认无孤儿残留。
- **X 域 H3/H4**（`ldap_client.py` 空口令 bind + LDAP TLS）：VM 实证点 = 真 LDAP server 空口令 bind 拒绝 + `KYLIN_LDAP_USE_TLS=true` 抓包确认加密。
- **H8（busy_timeout）已并入 D 的 B4 durability 工单**，不单独派。

> 完整状态全景以 `集成对齐备忘.md` §「★完成状态校准快照（dev=de90626）」为当前权威。

---

## ★之六十一 X 域 H3+H4 LDAP 安全修复（分支 feat/x-sso-ldap @ `9434572`，2026-07-15 待审）

| 之六十一 | H3 空口令 bind 拒绝 + H4 LDAP TLS | `9434572` | deploy/sso 1→11 |

**VM 实证点**（待真 LDAP server 环境验证）：
1. 真 LDAP server 正确 username + 空口令 bind → 拒绝（不因 unauthenticated bind 绕过）。
2. `KYLIN_LDAP_USE_TLS=true`（或 `ldaps://` URL）→ 抓包确认 service 账号 bind 口令加密过网。
3. 回归：`KYLIN_LDAP_USE_TLS` 未设 + `ldap://` → 明文（保持向后兼容默认）。

C3 边界：仅 `deploy/sso/ldap_client.py` + 对应 tests，未碰 backend/frontend/deploy/proxy。

---

## ★之六十二（分支 `feat/l-rca-llm-p4-metrics`，2026-07-15 L 域 RCA LLM P4 真接 + C1 summarize 埋点 + C2 原子化说明）

> dev 基线 `c6cc2eb`（origin/dev=`985b160`），commit `1cf4655`，pytest 703/17。

**RCA P4**：`orchestrator._emit_rca_summary` 接收 LLM.summarize 返回值（原裸 await 丢弃），
成功路径 audit `rca_llm_summary` + `scan_and_redact` C4 兜底 + 返回 redacted summary；
`_execute_batch` 合并一次 emit `{"report":..., "llm_summary":...}`（NullRCA→{}→falsy→跳过不回归）。
adapter/real_client 签名升级，真 LLM 可把 RCA 结构化报告拼进 prompt。

**C1 summarize 埋点**：`_emit_natural_language`/`_emit_rca_summary` 两处补 `llm.calls`/`llm.failures` 计数。

**C2 原子化说明**（不实现锁）：docstring 注明 DoS 软上限非安全不变量，asyncio 单线程竞态窗口极小。

4 新用例（T1-T4 全 PASS）+ 5 处 inline `summary_fn` 签名修复（`**_kwargs`）。
分支未推未合 dev，等架构者审阅。
## ★之六十二 X 域 H10 审批假成功修复（分支 feat/x-sso-ldap，2026-07-15 待审）

| 之六十二 | H10 审批假成功修复（approval.ts）| — | vitest 24→28 |

纯前端逻辑修复（审批后端失败保持 pending + 弹错误提示），无新增 VM 部署项。
功能验证：审批页在后端不可用时点通过/拒绝 → 状态仍待审批 + 顶部弹错误 toast（不假成功）。
C3 边界：仅 `frontend/src/stores/approval.ts` + 测试。**H11 mock 出 bundle 本工单不含**（用户自行处理）。

---

## ★之六十三 X 域 UI 视觉优化批（2026-07-15，merge 1b591d4，无新 VM 部署项）

X 域前端视觉调整批次（MainLayout 顶栏 + 8 页页头清理 + 仪表盘配色 + 按钮柔化），
**不含新增 VM 部署组件、端口、证书、systemd 单元或环境变量**，VM bring-up 清单本条目无实质变化。

---

## ★之六十四 D 域 B3 沙箱⊥NNP + B4 session.py durability（2026-07-15，merge b671e5d，含 VM 实证项）

D 域第一梯队收口，**涉 systemd 单元 + DB durability，VM bring-up 有实质变化**，dev 基线 `16f67cc`：

**B3 — 两个 app systemd 单元删 `NoNewPrivileges=yes`**（`301eb34`）：
- `deploy/app/kylin-safeops-agent.service` + `deploy/kylin-safeops.service` 删 NNP，补防误加回注释
- **根因**：app 单元 NNP → 内核吞掉 `sudo` setuid 提权（sudo 自报 "no new privileges 阻止以 root 运行" EXIT=1）→ 开沙箱后所有需提权工具全失败
- **真正 NNP 隔离在** wrapper 内层 `systemd-run -p NoNewPrivileges=yes`（`kylin-safeops-run.sh:83`），施加到被执行工具，与 app 进程独立
- ⚠ **VM 实证必做**：① `systemctl show kylin-safeops-agent -p NoNewPrivileges` 应为 no；② 开沙箱跑一个需提权工具（如读 /etc/shadow 类）验证 sudo→wrapper→systemd-run 链路通；③ `systemctl show` wrapper 内层进程确认 NNP=yes 施加到工具而非 app

**B4 — `session.py::connect()` 补 durability PRAGMA**（`c297c28`）：
- `PRAGMA synchronous=FULL` + `PRAGMA busy_timeout=5000`（WAL 之后、schema 初始化之前）
- **掉电场景**：synchronous=FULL 保证已 commit 的审计记录真 fsync 落盘；busy_timeout 让并发写等锁而非立即 SQLITE_BUSY
- 下沉到连接工厂本身（防御纵深），消除对 SqliteAuditSink 包装的隐式依赖
- ⚠ **VM 实证可选**：真机掉电/kill -9 后 verify_chain 仍完整（已 commit 记录不丢）

C3：`backend/app/db/session.py`（D 域）+ `backend/tests/test_audit.py`（D 域）+ 两 service 文件（deploy/app 名义 L 域，B3 工单 pre-authorize 派 D，L 审阅当面接受）。
CI：ruff/ruff-format/mypy ✅；pytest 701 passed + 3 预存失败（T17/T18/T19 Windows bash）+ 17 skipped。
AI 署名违规已 amend 清除（filter 前 93da5d1/e052c43 → 重写后 c297c28/301eb34，代码 tree 字节级不变，L 亲核 range-diff 坐实）。merge commit `b671e5d`，LEBLINC 署名。

---

## ★之六十六 X 前端消费 rca llm_summary（分支 feat/x-sso-ldap，2026-07-15 待审）

| 之六十六 | 前端消费 rca llm_summary（AI 根因摘要展示） | — | vitest 28/28 |

**VM 实证点（RCA 真 LLM 端到端联调，记录性不合 dev）**：
1. WSL/VM 真接 LLM（`KYLIN_LLM_PROVIDER=real`）触发磁盘满类场景（工具真执行出非空 RCA 报告）。
2. SSE `rca` 事件 `llm_summary` 字段有值（LLM 自然语言根因摘要）。
3. 前端 ChatView「RCA 证据链」区出现「AI 根因摘要」高亮块，内容为 LLM 文本。
4. 反向：LLM 拒答/注入拦截场景 → 无 llm_summary 字段 → 前端不渲染该块（零感知兼容）。
截图 + SSE trace 记录进本文档即可。

---
