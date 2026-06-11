# Kylin SafeOps Agent — L 模块设计文档（草稿）

> 范围：林泽远(L)负责的内核与 API 模块。据现有代码与提交记录据实起草，不夸大；
> 协作者(D/X)的 PolicyEngine / Executor / AuditSink 落库 / RCA / 前端仍为**注入桩**，文中如实标注。
> 跨窗口决策与接口冻结另见仓库根 `集成对齐备忘.md`（本文不重复造，按需引用）。
>
> 基线：dev=518e44f（L1/L2/L3 入库后）。本文随实现演进更新。

---

## 1. 总体架构与信任边界

### 1.1 定位

部署于 LoongArch + 麒麟服务器版 V11 的 B/S 安全智能运维 Agent。
核心叙事：**把大模型当"不可信顾问"而非"可信执行者"**。所有安全保证由确定性代码兜底
（策略引擎 + 最小权限 + 沙箱 + 哈希链审计）——即便 LLM 被提示注入完全攻陷、生成 `rm -rf /`，
也必须因策略/权限层拦截而无法造成实际损害。

### 1.2 信任边界

- **不可信区**：用户输入、LLM 输出、含外部数据的工具输出。
- **可信区**：策略引擎、特权代理(Executor)、审计。
- 跨越不可信 → 可信**只能**通过参数化、白名单化的工具调用（绝不拼裸 shell）。

### 1.3 模块归属

| 层 | 模块 | 归属 | 状态 |
|---|---|---|---|
| 契约(6) | `backend/app/contracts/` | L | 🟢 冻结 |
| LLM 网关 | `backend/app/llm/` | L | 🟢 真实 |
| 状态机 / 编排 | `backend/app/agent/` | L | 🟢 真实 |
| MCP 三道闸+结果闸 | `backend/app/mcp/` | L | 🟢 真实 |
| 感知工具(13) | `mcp_servers/os_ops/` | L | 🟢 ToolSpec+解析真实；执行委托 D |
| API 层 | `backend/app/api/` | L | 🟢 真实（认证为占位） |
| PolicyEngine.evaluate | `backend/app/security/` | D | 🔴 桩(allow-all) |
| Executor.execute | `backend/app/executor/` | D | 🔴 桩 |
| AuditSink 落库 | `backend/app/audit/` | D | 🟡 哈希链计算在 orchestrator 真实；落库桩 |
| RCAEngine / 前端 | X | X | 🟡 NullRCA 桩 / 前端骨架 |

---

## 2. 五道安全闸 → 代码落地映射

| 闸 | 职责 | 代码位置（L） | 状态 |
|---|---|---|---|
| ① 输入闸 | 结构化用户输入；LLM 仅产"工具名+结构化参数+理由" | `contracts/intent.py`(Intent extra=forbid) + `llm/adapter.py`(parse_intent/重试/降级) | 🟢 |
| ② 策略闸 | allow/deny/confirm 三态裁决 | `mcp/gateway.py` 调 `PolicyEngine.evaluate`；规则数据 `security/policy_rules.py`+`policy_loader.py`(DEFAULT_POLICY) | 🟡 evaluate 待 D；规则结构+默认集已在 |
| ③ 确认闸 | 高危(confirm)经人工审批才执行 | `agent/orchestrator.py`(WAIT_APPROVAL/resume) + `api/routers/approvals.py`(verify_approval_role 占位) | 🟢 流程真实；RBAC 占位 |
| ④ 结果闸 | 工具输出标记不可信 + 定界符封装 | `mcp/result_gate.py`(seal_result) + `contracts/untrusted.py`(ToolResult is_untrusted/wrap_token) + `llm/feedback.py`(回喂中和伪造定界符) | 🟢 |
| ⑤ 审计闸 | 每个状态转移点产哈希链记录 | `agent/orchestrator.py`(_append_audit) + `contracts/audit.py`(compute_curr_hash/canonical_json) | 🟢 计算真实；落库桩(FakeAudit) |

防御纵深补充：观测阶段经 `MCPGateway.is_read_only` 二次过滤——即便策略误放行变更工具，
观测也只执行只读(R0/R1)工具；手动 `/api/tools/call` 同样设只读门，变更工具只能走 chat→审批链路。

---

## 3. 六份契约职责 + 关键字段

位于 `backend/app/contracts/`，均 pydantic v2 + `ConfigDict(extra="forbid")`（防字段偷渡）。

1. **tool.py — ToolSpec**（工具静态描述，唯一事实来源）
   - `name` / `description` / `risk`(R0–R4) / `input_schema`(强类型 JSON Schema，禁任意路径命令) / `requires_roles` / `reversible`。
2. **intent.py — Intent / CandidateTool**（LLM 结构化意图）
   - Intent: `intent` / `confidence` / `need_observation` / `candidate_tools` / `risk_hint` / `justification`。
   - CandidateTool: `name`(须匹配已注册 ToolSpec) / `args`(按 input_schema 校验)。**绝不含裸 shell 字段**。
3. **policy.py — PolicyVerdict / PolicyEngine(Protocol)**（三态裁决）
   - Decision = allow/deny/confirm；`final_risk` / `matched_rules` / `reason` / `safer_alternative` / `approval_required` / `approval_role`。
   - `PolicyEngine.evaluate(tool) -> PolicyVerdict`（**同步**，确定性、无副作用）。
4. **untrusted.py — ToolResult**（结果闸产物）
   - `tool` / `args` / `exit_code` / `stdout_truncated` / `is_untrusted`(默认 True) / `wrap_token`。
5. **audit.py — AuditRecord + 哈希链**
   - `trace_id` / `seq` / `phase` / `payload` / `prev_hash` / `curr_hash`；
   - `curr = SHA256(prev ∥ canonical_json(payload))`；`GENESIS_HASH`。
6. **stream.py — StreamEvent**（前端事件流）
   - 11 种 EventType；`trace_id` / `type` / `ts` / `data`。多工具形态：`policy_verdict.per_tool` / `await_approval.tools` / `executing.tools`。

---

## 4. orchestrator 状态机与编排（`backend/app/agent/`）

### 4.1 状态机（11 态，`state_machine.py`）

```
RECEIVED → INTENT_PARSED → CONTEXT_COLLECTED → PLAN_GENERATED → POLICY_CHECKED
  → WAIT_APPROVAL / REJECTED / EXECUTING → EXECUTED → VERIFIED → FINISHED
```
- 纯定义层：状态枚举 + 合法转移表 + 校验函数，**无 IO**。
- 终态：`REJECTED` / `FINISHED`（无出边）。
- POLICY_CHECKED 三出口：allow→EXECUTING / confirm→WAIT_APPROVAL / deny→REJECTED。
- WAIT_APPROVAL 两出口：批准→EXECUTING / 拒绝→REJECTED。
- 状态与 EventType **非一一对应**：RECEIVED/REJECTED/FINISHED 无独立前端事件，仅产审计。

### 4.2 observe→re-plan 多轮（有界，`orchestrator.py`）

- 在 CONTEXT_COLLECTED 内循环（不新增状态、不重复 _goto）：每轮经 gateway 只读防御纵深采集观测
  → 安全封装(`wrap_many_for_feedback`)回喂 → 二次规划。
- 上限 `max_observation_rounds`(默认 3)。终止条件（任一即停进入规划）：
  ① 二次规划 `need_observation=False`；② 无候选工具；③ 候选与刚观测的指纹一致(planner 未推进)；
  ④ 达轮次上限（双重防死循环）。指纹 = `_candidates_key`(名+规范化 args)。

### 4.3 多工具"原子计划"

- 逐候选各自裁决(`_evaluate_all`)；整批决策 = 最严裁决(`most_restrictive`：deny>confirm>allow)。
- 含 deny → 整批 REJECTED，**不部分执行**（安全优先）。
- confirm → WAIT_APPROVAL，审批面板列出的工具 == 批准后执行的同一批（消除错配）。
- allow → 整批按序执行；每工具各自留痕(审计 + tool_result 事件)。
- 方案 B：单工具失败以 `exit_code != 0` 承载，由 VERIFIED 聚合判定；仅系统级故障 raise→error 事件终止。

### 4.4 RCA 接入点

- 执行后把累积证据(`_evidence`，全部 is_untrusted)交注入的 `RCAEngine.analyze`；
- 返回非空 dict 才 emit `rca` 事件。当前为 `NullRCA` 桩（返回 {}）；真 RCA 编排归 X。

---

## 5. MCP 网关：三道闸 + 结果闸（`backend/app/mcp/`）

`MCPGateway(registry, policy, executor)`，`tools/call` 强制顺序（不可调换）：
1. **闸1 注册校验**：工具必须已注册（防影子工具）。
2. **闸2 结构校验**：args 按 `ToolSpec.input_schema` 过 `schema_validator`（路径 canonicalize + 禁 `..`）。
3. **闸3 策略放行**：过 `PolicyEngine.evaluate`；deny 永拦、confirm 仅在已审批(approved=True)放行、allow 放行。
- 放行后交 `Executor.execute`，结果一律经 `seal_result` 密封(is_untrusted=True + 标准 wrap_token)。
- 本层不跑命令、不拼 shell（铁律）；执行委托 D 的 Executor。
- `evaluate(tool)` 供 orchestrator 在 POLICY_CHECKED 阶段裁决（不执行）；gateway 是权威执行边界，
  即便 orchestrator 先 evaluate 过，`call` 仍重新过闸（防御纵深，要求 evaluate 确定性两次一致）。

---

## 6. API 层（`backend/app/api/`）

把 orchestrator 内核包装为 B/S 服务（FastAPI + uvicorn，纯 Python，避 LoongArch C 扩展）。

### 6.1 关键组件

- **事件总线** `event_bus.py`：按 `trace_id` 分发的内存 `asyncio.Queue`（None=终止哨兵）；
  `SSEEventSink` 实现 EventSink，把 orchestrator emit 的 StreamEvent 投递到对应队列。
- **SSE** `sse_stream`：纯 Starlette `StreamingResponse`（未引 sse-starlette）；
  `await queue.get()` 阻塞保持 HTTP 连接(审批期保活)，resume 后续推同队列；15s 心跳防代理断连；
  done 哨兵正常结束。已知限制：无 Last-Event-ID 回放、单消费者（多 SSE 瓜分事件）——待 L 决策(Q-X3)。
- **会话存活注册表** `session_registry.py`：保持 Orchestrator 实例存活(run 返回 WAIT_APPROVAL 后不销毁)，
  resume 取回同一实例；终态 + 超时清理（与队列同生命周期，防泄漏）。
- **对话会话表** `session_store.py`：前端左侧会话列表(session_id 主键)，与上者严格区分。

### 6.2 端点

| 方法 路径 | 职责 |
|---|---|
| POST `/api/chat` | 建 trace_id + 后台 `asyncio.create_task(run)` + 返回 trace_id/stream_url；后台异常兜底(emit error+close 防 SSE 挂死) |
| GET `/api/chat/{trace_id}/events` | SSE 事件流；`request.is_disconnected()` 断连即 bus.remove |
| POST `/api/approvals/resume` | 取同一 Orchestrator 调 resume，事件续推同一 SSE；404/409 守卫；挂 `verify_approval_role` |
| GET `/api/tools/registry` | 列举工具（字段适配 `ToolSpec.name → tool`） |
| POST `/api/tools/call` | 手动单工具调用，经三道闸；**只读门**：变更工具(R2+)拦在外，须走 chat→审批 |
| GET/POST/GET/PATCH/DELETE `/api/chat/sessions[/{id}]` | 会话 CRUD（内存版，404 守卫） |
| GET `/api/system/overview` | Dashboard 概览（当前桩数据，TODO 接 os_ops 聚合） |
| POST `/api/rca/analyze` · GET `/api/rca/{trace_id}` | RCA 入口（NullRCA 桩，report 结构待 X） |

### 6.3 认证占位（安全红线，不静默无防护）

- 所有端点挂 `Depends(verify_token)`；审批端点加 `verify_approval_role`。
- 当前为**占位放行**，启动 `logger.warning` 显式标注"认证未接入，仅限内网/联调"。
- TODO(BLOCKED-ON-D)：接 D 的 RBAC 校验调用者角色 == `verdict.approval_role`。

---

## 7. 注入桩与 fake→real 切换点

详见 `集成对齐备忘.md §3`（审阅窗口维护，唯一事实来源），此处仅索引：

- 替换面收敛于 `backend/app/api/_fakes.py` + `app.py` 的 provider：
  - 策略：`build_fake_gateway()` 的 `FakePolicyEngine` → `PolicyEngine(DEFAULT_POLICY, registry)`；
  - 执行：`FakeExecutor` → D 的真 Executor；
  - 审计：`get_audit()` 的 `FakeAudit` → D 的真 AuditSink（届时 provider 升为 lifespan 单例）；
  - RCA：`api/routers/rca.py` 的 `NullRCA` → X 的真 RCA。
- **L1 集成验收哨兵** `backend/tests/test_e2e_real_policy.py`：D 的 PolicyEngine 一从
  `backend.app.security` 导出即自动激活（当前 module-level skip），断言即规格。

---

## 8. 演示剧本（D16，`scripts/`）

四场景 happy-path 管道串联（跑在 fake 上，公共装配 `scripts/_demo_common.py`）：

| 场景 | 剧本 | 管道 | 终态 |
|---|---|---|---|
| ① 磁盘满 | `demo_disk_full_playbook.py` | 观测 disk.usage → log.compress_rotate(R2,confirm/operator)→审批→执行 | FINISHED |
| ② 僵尸进程 | `demo_zombie_process_playbook.py` | 观测 process.list → service.restart(R3,confirm/admin)→审批→执行 | FINISHED |
| ③ 磁盘 I/O | `demo_disk_io_playbook.py` | **近似**(无 iostat/iotop)：process.list(cpu) → service.restart(R3) | FINISHED |
| ④ 配置漂移 | `demo_config_drift_playbook.py` | 单段只读 config.hash_snapshot + config.diff(R0,allow) | FINISHED |

- ★场景③局限：os_ops 13 工具无真正 I/O 感知工具，剧本头已标注"近似演示 / TODO 待补 io.stat"。
- 回归测试 `backend/tests/test_demo_playbook.py` 只断言终态 + 执行序（不写安全拦截硬断言）。

---

## 9. 待办 / 桩清单（如实标注）

- 🔴 PolicyEngine.evaluate（D，PR1）；🔴 Executor.execute（D，PR2）；🟡 AuditSink 落库（D，PR3）。
- 🟡 RCAEngine（X）/ 前端接真 API（X）。
- API 认证 RBAC（D）；system/overview 真实采集；SSE 重连续传(Q-X3)。
- 场景③ I/O 感知工具是否补（交 L 判）。
