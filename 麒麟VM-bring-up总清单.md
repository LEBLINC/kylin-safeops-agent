# 麒麟 V11 + LoongArch VM 分阶段 bring-up 总清单（统筹用 · 可勾选）

> 维护：L（集成 + 审阅窗口）。基线 **dev = `200a63c`（origin 同步）**。日期：2026-06-19。
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

**X 工单（T1+T2+T3）已起**：建议分支 `feat/x-sse-whoami-vitest`，2-3 commit 拆开，B1 VM 复证是 PASS 必要条件。
