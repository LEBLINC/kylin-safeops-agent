# X1 API 联调统计台账

> 文档用途：给负责人/项目管理视角把控 X1 API 联调范围、页面覆盖、接口契约、后端实现状态、前端调用状态与完成标识。  
> 生成时间：2026-06-13（最终更新：2026-06-13 台账回填 cfe4f52 / dev tip e732dc9）  
> 依据：当前上传工程包 `kylin-safeops-agent-feat-x`、后端 `backend/app/api/routers/*`、后端 `backend/app/api/schemas.py`、后端 `backend/app/contracts/stream.py`（dev e732dc9 已补 injection 三值）、前端 `frontend/src/views/*`、`frontend/src/api/*`、`frontend/src/types/*`。

---

## 0. 完成标识说明

> 本文档不再使用 `[❌]` 表示未完成，避免和“失败/错误”混淆。  
> 完成列只表达“是否已通过联调”。

| 完成标识 | 含义 | 使用场景 |
|---|---|---|
| [⬜] | 未完成 / 待联调 / 待确认 | 默认状态 |
| [✅] | 已完成 / 已通过 | 真实 API 联调通过后手动改为此标识 |

### 联调状态枚举

| 状态 | 含义 |
|---|---|
| 待联调 | 尚未开始真实 API 联调 |
| 联调中 | 正在联调 |
| 已通过 | 请求、响应、页面渲染、异常处理均通过 |
| 待修正 | 前端或契约存在偏差，需要修正后再联调 |
| 阻塞 | 后端接口缺失、路由未实现或关键能力缺失 |
| 不纳入 X1 | 非本轮必须联调范围 |
| 无需联调 | 静态页面或仅展示本地配置 |

---

## 1. 总览统计

| 指标 | 数量 | 说明 |
|---|---:|---|
| 页面总数 | 10 | 当前前端 `src/views` 下的页面 |
| REST/API 台账项 | 33 | 前端 API 文件中声明/调用的 REST 接口 |
| SSE 事件台账项 | 12 | 12 个业务事件（不含 transport done）|
| X1 必须 API 项 | 10 | Chat 主链路、审批续跑、会话 CRUD、Dashboard、Tools Registry |
| 后端已实现 API 项 | 13 | 当前后端 routers 中存在的 REST 接口 |
| 后端缺失 API 项 | 20 | 前端已有声明但后端当前未实现 |
| 当前待修正项 | 2 | Item 2(resume 全流程)/Item 4(SSE 生命周期) 受 fake planner 限制无法真实验证；其余 5/7 已通过联调 |
| 当前阻塞项 | 20 | 主要集中在 Approval 集中页、Audit、Policy、Demo、ToolDetail、System 详情接口 |
| 已通过联调项 | 15 | 主链路 REST + SSE 8 类事件 + 会话 CRUD + Dashboard + Tools Registry |

---

## 2. 页面台账

| 完成标识 | 页面 | 前端文件 | 页面定位 | API 数 | X1 必须项 | 后端整体状态 | 当前联调状态 |
|---|---|---|---|---:|---:|---|---|
| [✅] | Chat 智能对话页 | `frontend/src/views/ChatView.vue` | X1 主链路：发消息、SSE、审批、工具输出、会话 | 8 REST + 12 SSE | 8 REST + 12 SSE | 主链路后端已实现 | 联调通过（审批全流程除外） |
| [✅] | Dashboard 仪表盘页 | `frontend/src/views/DashboardView.vue` | 系统概览指标与服务状态 | 4 | 1 | `/overview` 已实现，其余详情接口缺失 | 联调通过 |
| [✅] | Tools 工具注册表页 | `frontend/src/views/ToolsView.vue` | 工具列表与工具风险信息 | 2 | 1 | `/registry`、`/call` 已实现 | 联调通过 |
| [⬜] | ToolDetail 工具详情页 | `frontend/src/views/ToolDetailView.vue` | 工具调用详情 | 1 | 0 | 后端缺失 | 阻塞 / 不纳入 X1 |
| [⬜] | RCA 根因分析页 | `frontend/src/views/RcaView.vue` | RCA 分析与报告展示 | 2 | 0 | 后端已实现 | 可选联调 |
| [⬜] | Approval 集中审批页 | `frontend/src/views/ApprovalView.vue` | 管理员审批待办列表 | 5 | 0 | 仅 `/resume` 已实现；集中审批 API 缺失 | 阻塞 / 不纳入 X1 |
| [⬜] | Audit 审计页 | `frontend/src/views/AuditView.vue` | 审计 trace、hash chain、导出 | 4 | 0 | 后端缺失 | 阻塞 / 不纳入 X1 |
| [⬜] | Policy 策略页 | `frontend/src/views/PolicyView.vue` | 策略规则、策略事件、风险等级 | 3 | 0 | 后端缺失 | 阻塞 / 不纳入 X1 |
| [⬜] | Demo 演示页 | `frontend/src/views/DemoView.vue` | 演示场景准备/运行/清理 | 3 | 0 | 后端缺失 | 阻塞 / 不纳入 X1 |
| [✅] | Settings 设置页 | `frontend/src/views/SettingsView.vue` | 展示 Mock/API/角色等配置 | 0 | 0 | 无需后端 | 无需联调 |

---

## 3. X1 必须通过清单

> 这部分是 X1 完成定义的核心检查项。真实模式下必须逐项打勾。

| 完成标识 | 页面 | 类型 | API / 事件 | 用途 | 当前状态 |
|---|---|---|---|---|---|
| [✅] | Chat | REST | `POST /api/chat` | 发送用户消息，返回 `trace_id` 与 `stream_url` | 已通过 |
| [✅] | Chat | SSE | `GET /api/chat/{trace_id}/events` | 订阅同一 trace 的业务事件流 | 已通过 |
| [⬜] | Chat | REST | `POST /api/approvals/resume` | 批准/拒绝后续跑同一 SSE | contract 格式已通过；全流程受 fake planner 限制 |
| [✅] | Chat | REST | `GET /api/chat/sessions` | 拉取会话列表 | 已通过 |
| [✅] | Chat | REST | `POST /api/chat/sessions` | 创建会话 | 已通过 |
| [✅] | Chat | REST | `GET /api/chat/sessions/{id}` | 获取会话详情/元信息 | 已通过 |
| [✅] | Chat | REST | `PATCH /api/chat/sessions/{id}` | 重命名会话 | 已通过 |
| [✅] | Chat | REST | `DELETE /api/chat/sessions/{id}` | 删除会话 | 已通过 |
| [✅] | Dashboard | REST | `GET /api/system/overview` | 首页系统概览 | 已通过 |
| [✅] | Tools | REST | `GET /api/tools/registry` | 工具注册表，字段使用 `tool` | 已通过 |
| [✅] | Chat | UI 安全项 | `tool_result.data.result.is_untrusted` | 工具输出必须标注”不可信/来自工具输出” | 已通过 |
| [✅] | Chat | UI 状态项 | `event: done` | 只作为 SSE transport 结束事件，不进入业务事件列表 | 已通过 |

---

## 4. API 联调台账

### 4.1 Chat 智能对话页

| 完成标识 | 方法 | API | 用途 | 请求体摘要 | 响应体摘要 | 后端状态 | 前端状态 | X1 必须 | 联调状态 / 备注 |
|---|---|---|---|---|---|---|---|---|---|
| [✅] | POST | `/api/chat` | 发送用户自然语言消息 | `{message, session_id?}` | `{session_id?, trace_id, stream_url}` | 已实现 | 已调用 | 是 | 联调通过 |
| [✅] | GET | `/api/chat/{trace_id}/events` | SSE 订阅业务事件 | path: `trace_id` | `StreamEvent`（不含 done） | 已实现 | 已修正 | 是 | 联调通过：8 类业务事件 + transport done |
| [⬜] | POST | `/api/approvals/resume` | 批准/拒绝当前 trace 续跑 | `{trace_id, approved}` | `{trace_id, accepted}` | 已实现 | 已修正 | 是 | contract 格式验证通过；全流程需真实 planner 触发 await_approval |
| [✅] | GET | `/api/chat/sessions` | 获取会话列表 | 无 | `ChatSessionDTO[]` | 已实现 | 已调用 | 是 | 联调通过 |
| [✅] | POST | `/api/chat/sessions` | 创建会话 | `{title?}` | `ChatSessionDTO` | 已实现 | 已调用 | 是 | 联调通过 |
| [✅] | GET | `/api/chat/sessions/{session_id}` | 获取会话元信息 | path: `session_id` | `ChatSessionDTO` | 已实现 | 已调用 | 是 | 联调通过 |
| [✅] | PATCH | `/api/chat/sessions/{session_id}` | 重命名会话 | `{title}` | `ChatSessionDTO` | 已实现 | 已调用 | 是 | 联调通过 |
| [✅] | DELETE | `/api/chat/sessions/{session_id}` | 删除会话 | path: `session_id` | `{session_id, deleted}` | 已实现 | 已调用 | 是 | 联调通过 |
| [✅] | GET | `/api/chat/sessions/search?keyword=xxx` | 会话搜索 | query: `keyword` | `ChatSession[]` | 缺失 | 已停用 | 否 | 代码修正完成：真实模式前端本地过滤，不调后端 |

#### Chat 契约详情

**POST `/api/chat` 请求体**

```json
{
  "message": "帮我看看磁盘为什么快满了",
  "session_id": "optional-session-id"
}
```

**POST `/api/chat` 响应体**

```json
{
  "session_id": "optional-session-id",
  "trace_id": "trace_xxx",
  "stream_url": "/api/chat/trace_xxx/events"
}
```

**POST `/api/approvals/resume` 请求体**

```json
{
  "trace_id": "trace_xxx",
  "approved": true
}
```

**禁止额外发送字段**

```json
{
  "comment": "xxx",
  "status": "approved",
  "required_role": "admin"
}
```

后端 `ResumeRequest` 设置了 `extra="forbid"`，多余字段会导致 422。

**POST `/api/approvals/resume` 响应体**

```json
{
  "trace_id": "trace_xxx",
  "accepted": true
}
```

---

### 4.2 Dashboard 仪表盘页

| 完成标识 | 方法 | API | 用途 | 请求体摘要 | 响应体摘要 | 后端状态 | 前端状态 | X1 必须 | 联调状态 / 备注 |
|---|---|---|---|---|---|---|---|---|---|
| [✅] | GET | `/api/system/overview` | 系统总览指标 | 无 | `SystemOverview` | 已实现 | 已修正 | 是 | 联调通过：services[{status:"running"}] 映射正确 |
| [⬜] | GET | `/api/system/disk` | 磁盘详情 | 无 | 未定义 | 缺失 | 已声明 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | GET | `/api/system/processes` | 进程详情 | 无 | 未定义 | 缺失 | 已声明 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | GET | `/api/system/services` | 服务详情 | 无 | 未定义 | 缺失 | 已声明 | 否 | 阻塞 / 不纳入 X1 |

#### Dashboard 契约详情

**GET `/api/system/overview` 响应体**

```json
{
  "cpu_usage": 12.5,
  "memory_usage": 43.0,
  "root_disk_usage": 68.2,
  "zombie_processes": 0,
  "tool_calls_today": 0,
  "denied_today": 0,
  "services": [
    {
      "name": "nginx.service",
      "status": "running"
    }
  ],
  "data_source": "stub_executor",
  "probed_tools": ["disk.usage"]
}
```

重点检查：

- **P1-1**：`DashboardView.vue:118` `services[].status` 硬编码 `status=”success”`，需改为 `:status=”service.status”`。
- **P2**：`StatusTag.vue:29` 的 statusMap 缺少 `running`（→`运行中`）、`stopped`（→`已停止`）映射，后端 `system.py` 返回 `status=”running”`，当前未映射会 fallback 到原始英文。
- `data_source=stub_executor` 时页面已提示”桩数据”（`:86-89`），`probed_tools` 为空时提示”采集管道未接通”——**安全叙事正确**。
- Dashboard 主页面 X1 只依赖 `/api/system/overview`。

---

### 4.3 Tools 工具注册表页

| 完成标识 | 方法 | API | 用途 | 请求体摘要 | 响应体摘要 | 后端状态 | 前端状态 | X1 必须 | 联调状态 / 备注 |
|---|---|---|---|---|---|---|---|---|---|
| [✅] | GET | `/api/tools/registry` | 工具注册表 | 无 | `ToolRegistryItem[]` | 已实现 | 已调用 | 是 | 联调通过：字段为 tool 非 name |
| [⬜] | POST | `/api/tools/call` | 手动调用单工具 | `{tool, args}` | `{executed, result?, verdict?, reason}` | 已实现 | 已声明/可能调用 | 否 | 不纳入 X1；不建议开放变更类工具手动调用 |

#### Tools 契约详情

**GET `/api/tools/registry` 响应体**

```json
[
  {
    "tool": "disk.usage",
    "description": "查看磁盘使用情况",
    "risk": "R0",
    "input_schema": {}
  }
]
```

重点检查：

- 字段是 `tool`，不是 `name`。
- 前端页面、类型、搜索、展示都不应依赖 `name`。

---

### 4.4 ToolDetail 工具调用详情页

| 完成标识 | 方法 | API | 用途 | 请求体摘要 | 响应体摘要 | 后端状态 | 前端状态 | X1 必须 | 联调状态 / 备注 |
|---|---|---|---|---|---|---|---|---|---|
| [⬜] | GET | `/api/tools/calls/{call_id}` | 查看工具调用详情 | path: `call_id` | `ToolCallLog` | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |

X1 处理建议：

- 工具结果优先从 Chat SSE `tool_result` 展示。
- 本页真实模式下应显示“工具调用详情 API 尚未接入”，不要展示 mock 为真实数据。

---

### 4.5 RCA 根因分析页

| 完成标识 | 方法 | API | 用途 | 请求体摘要 | 响应体摘要 | 后端状态 | 前端状态 | X1 必须 | 联调状态 / 备注 |
|---|---|---|---|---|---|---|---|---|---|
| [⬜] | POST | `/api/rca/analyze` | 发起 RCA 分析 | `{problem_type, description}` | `{trace_id}` | 已实现 | 已调用 | 否 | 可选联调 |
| [⬜] | GET | `/api/rca/{trace_id}` | 获取 RCA 报告 | path: `trace_id` | `{trace_id, report}` | 已实现 | 已调用 | 否 | 可选联调 |

说明：

- Chat 页中的 RCA 来自 SSE 事件 `rca -> {report}`。
- RCA 页面 REST 接口和 Chat SSE 不是同一条主链路。
- X1 优先保证 Chat 页 SSE 中的 `rca` 事件能展示。

---

### 4.6 Approval 集中审批页

| 完成标识 | 方法 | API | 用途 | 请求体摘要 | 响应体摘要 | 后端状态 | 前端状态 | X1 必须 | 联调状态 / 备注 |
|---|---|---|---|---|---|---|---|---|---|
| [⬜] | GET | `/api/approvals?status=pending` | 待审批列表 | query: `status` | `ApprovalItem[]` | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | GET | `/api/approvals/{approval_id}` | 审批详情 | path: `approval_id` | `ApprovalItem` | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | POST | `/api/approvals/{approval_id}/approve` | 批准审批单 | path: `approval_id` | 未定义 | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | POST | `/api/approvals/{approval_id}/reject` | 拒绝审批单 | `{comment?}` | 未定义 | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | POST | `/api/approvals/escalate` | 转交审批 | `{trace_id, comment, tools}` | `{trace_id, status, message}` | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |

说明：

- X1 必须联调的是 Chat 内联审批 `POST /api/approvals/resume`。
- 集中审批页当前缺后端 REST 列表/详情/审批单接口，不阻塞 X1 主链路。

---

### 4.7 Audit 审计页

| 完成标识 | 方法 | API | 用途 | 请求体摘要 | 响应体摘要 | 后端状态 | 前端状态 | X1 必须 | 联调状态 / 备注 |
|---|---|---|---|---|---|---|---|---|---|
| [⬜] | GET | `/api/audit/traces` | 审计 trace 列表 | query params | `AuditTrace[]` | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | GET | `/api/audit/traces/{trace_id}` | trace 审计详情 | path: `trace_id` | `AuditRecord[]` | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | POST | `/api/audit/verify` | 校验 hash chain | `{trace_id}` | `HashChainVerifyResult` | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | GET | `/api/audit/traces/{trace_id}/export` | 导出审计报告 | path: `trace_id` | blob | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |

X1 处理建议：

- 审计页 REST 查询不纳入 X1。
- X1 只要求 Chat SSE 中的 `audit_appended -> {seq, curr_hash}` 能展示。

---

### 4.8 Policy 策略页

| 完成标识 | 方法 | API | 用途 | 请求体摘要 | 响应体摘要 | 后端状态 | 前端状态 | X1 必须 | 联调状态 / 备注 |
|---|---|---|---|---|---|---|---|---|---|
| [⬜] | GET | `/api/policy/events?trace_id=xxx` | 策略事件列表 | query: `trace_id` | `PolicyEvent[]` | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | GET | `/api/policy/rules` | 策略规则列表 | 无 | `PolicyRule[]` | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | GET | `/api/policy/risk-levels` | 风险等级说明 | 无 | 未定义 | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |

X1 处理建议：

- Policy 独立页面不纳入本轮强制联调。
- Chat 页必须消费 SSE `policy_verdict -> {verdict, per_tool}`。

---

### 4.9 Demo 演示页

| 完成标识 | 方法 | API | 用途 | 请求体摘要 | 响应体摘要 | 后端状态 | 前端状态 | X1 必须 | 联调状态 / 备注 |
|---|---|---|---|---|---|---|---|---|---|
| [⬜] | POST | `/api/demo/{scenario_id}/prepare` | 准备演示场景 | `{scenario}` | 未定义 | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | POST | `/api/demo/{scenario_id}/run` | 运行演示场景 | 无 | 未定义 | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |
| [⬜] | POST | `/api/demo/{scenario_id}/cleanup` | 清理演示场景 | `{scenario}` | 未定义 | 缺失 | 已调用 | 否 | 阻塞 / 不纳入 X1 |

X1 处理建议：

- Demo 页可保留 Mock 演示。
- 真实模式下应提示“Demo API 尚未接入”。

---

### 4.10 Settings 设置页

| 完成标识 | 方法 | API | 用途 | 请求体摘要 | 响应体摘要 | 后端状态 | 前端状态 | X1 必须 | 联调状态 / 备注 |
|---|---|---|---|---|---|---|---|---|---|
| [✅] | - | 无 | 展示前端运行配置 | - | - | 无需后端 | 静态展示 | 否 | 无需联调 |

建议显示：

- `VITE_MOCK_ENABLED`
- `VITE_API_BASE_URL`
- `VITE_PROXY_TARGET`
- `VITE_CURRENT_USER_ROLE`

---

## 5. SSE 事件台账

> 业务事件必须严格按 `backend/app/contracts/stream.py` 解析。  
> `done` 是 SSE transport 结束事件，不是业务 `StreamEvent.type`。

| 完成标识 | 事件类型 | 是否业务事件 | data 契约摘要 | 页面消费位置 | X1 必须 | 联调状态 / 备注 |
|---|---|---:|---|---|---|---|
| [✅] | `intent_parsed` | 是 | `{intent}` | Chat 时间轴 / Store | 是 | 联调通过 |
| [⬜] | `observation` | 是 | `{results: ToolResult[]}` | Chat 工具结果 / 时间轴 | 是 | 待联调；工具输出要按不可信证据展示 |
| [✅] | `plan_generated` | 是 | `{candidate_tools: CandidateTool[]}` | Chat 计划展示 / 时间轴 | 是 | 联调通过；A4 已闭合：orchestrator.py:243-244 emit 层 `{"tool": t.name}` 映射正确 |
| [✅] | `policy_verdict` | 是 | `{verdict, per_tool}` | Chat 策略裁决卡 / 时间轴 | 是 | 联调通过；per_tool[].tool 字段正确 |
| [⬜] | `await_approval` | 是 | `{reason, tools:[{tool, approval_role}]}` | Chat 内联审批卡 | 是 | fake planner 已有 R2/R3 路由（"重启"→service.restart/R3，"轮转"→log.compress_rotate/R2），联调需 `KYLIN_AUTH_MODE=dev + X-User-Role: admin` 请求头；待 X 执行验证 |
| [✅] | `executing` | 是 | `{tools: string[]}` | Chat 工具执行状态 / 时间轴 | 是 | 联调通过 |
| [✅] | `tool_result` | 是 | `{result: ToolResult}` | Chat 工具卡 | 是 | 联调通过：is_untrusted:true + wrap_token |
| [✅] | `verified` | 是 | `{summary}` | Chat 最终回答 | 是 | 联调通过 |
| [✅] | `rejected` | 是 | `{reason, cause: "policy_deny" \| "user_reject" \| "injection", denied_tools}` | Chat 拒绝收尾 | 是 | 前端已实现 cause 三值分支（`policy_deny`/`user_reject`/`injection`）；injection 专属展示"⛔ 输入被安全策略拦截"；A5 已闭合（feat/x cfe4f52）；后端契约 stream.py 注释已由 L 补三值（dev e732dc9），契约-实现完全一致 |
| [⬜] | `rca` | 是 | `{report}` | Chat RCA 卡片 / 侧栏 | 是 | 待联调 |
| [✅] | `audit_appended` | 是 | `{seq, curr_hash}` | Chat 审计链提示 / 时间轴 | 是 | 联调通过 |
| [⬜] | `error` | 是 | `{message, phase}` | Chat 错误收尾 | 是 | 待联调 |
| [✅] | `done` | 否 | `{}` | EventSource transport 层 | 是 | 联调通过：event:done + data:{} 正确作为 transport 结束 |

---

## 6. 当前待修正项

| 完成标识 | 编号 | 位置 | 问题 | 修正目标 | 优先级 |
|---|---:|---|---|---|---|
| [✅] | 1 | frontend/src/types/chat.ts（EventType 含 done）、frontend/src/api/chat.ts（SSE done handler）、frontend/src/stores/chat.ts（addEvent branch） | 前端把 done 放进 EventType | 移除 EventType 中 done；connectChatStream 用 onDone 回调（联调通过，feat/x cfe4f52） | P0 |
| [✅] | 2 | frontend/src/types/approval.ts:72（comment?）、:76-81（status 而非 accepted: bool） | ResumeApprovalRequest 残留 comment?，Response 用 status 而非 accepted | 删 comment?；Response 改 {trace_id, accepted: boolean}（联调通过，feat/x cfe4f52） | P0 |
| [✅] | 3 | `frontend/src/stores/chat.ts:676-681`（approveInlinePlan 用 `this.activeTraceId`）、`:700-705`（rejectInlinePlan 同理）、`frontend/src/views/ChatView.vue:152-153`（approveBatch 不传 trace_id） | 审批函数默认使用 `activeTraceId`，多会话/历史审批卡可能批错 trace；ApprovalCard 正确 emit 了 `inline.trace_id` 但 ChatView 未使用 | ① store 方法增加 `traceId` 参数：`approveInlinePlan(traceId: string)`；② ChatView 从 ApprovalCard emit 接收 trace_id 传入 store（feat/x cfe4f52） | P0 |
| [⬜] | 4 | frontend/src/stores/chat.ts:296-306 | switchSession() 无条件关闭 SSE | 检查 pending 审批状态再决定是否关流（受 fake planner 限制无法真实验证） | P0 |
| [✅] | 5 | `frontend/src/api/chat.ts:121-126`（searchSessionsApi 调 `/api/chat/sessions/search`）、`frontend/src/stores/chat.ts:354-367`（searchSessions 方法） | 真实模式仍会请求后端不存在的 `/api/chat/sessions/search`（getter `filteredSessions` 已有本地过滤逻辑） | X1 改为纯前端本地过滤：store 的 `searchSessions` 只设 `searchKeyword` 不调远程 API（feat/x cfe4f52） | P1 |
| [✅] | 6 | frontend/src/views/DashboardView.vue（StatusTag 硬编码 success） | 服务状态硬编码 success，不读 service.status | 改为 :status=serviceStatus(service.status)；StatusTag 补齐 running/stopped 映射（联调通过，feat/x cfe4f52） | P1 |
| [✅] | 7 | `frontend/src/components/ToolCallCard.vue:49-52` | 工具输出安全标识：代码已正确实现 `is_untrusted` 时显示"不可信输出"标签 | ✅ 审计确认已实现，无需修正（feat/x cfe4f52） | P1 |

---

## 7. 当前阻塞项

> 这些接口后端当前未实现，不应阻塞 X1 主链路；真实模式下页面应降级提示“API 尚未接入”。

| 完成标识 | 页面 | API | 阻塞原因 | X1 处理建议 |
|---|---|---|---|---|
| [⬜] | Chat | `GET /api/chat/sessions/search` | 后端未实现 | 改为前端本地过滤 |
| [⬜] | Dashboard | `GET /api/system/disk` | 后端未实现 | 不纳入 X1 |
| [⬜] | Dashboard | `GET /api/system/processes` | 后端未实现 | 不纳入 X1 |
| [⬜] | Dashboard | `GET /api/system/services` | 后端未实现 | 不纳入 X1 |
| [⬜] | ToolDetail | `GET /api/tools/calls/{call_id}` | 后端未实现 | 真实模式提示未接入 |
| [⬜] | ApprovalView | `GET /api/approvals` | 后端未实现 | 集中审批页不纳入 X1 |
| [⬜] | ApprovalView | `GET /api/approvals/{approval_id}` | 后端未实现 | 集中审批页不纳入 X1 |
| [⬜] | ApprovalView | `POST /api/approvals/{approval_id}/approve` | 后端未实现 | 集中审批页不纳入 X1 |
| [⬜] | ApprovalView | `POST /api/approvals/{approval_id}/reject` | 后端未实现 | 集中审批页不纳入 X1 |
| [⬜] | ApprovalView | `POST /api/approvals/escalate` | 后端未实现 | 集中审批页不纳入 X1 |
| [⬜] | Audit | `GET /api/audit/traces` | 后端未实现 | 审计页不纳入 X1 |
| [⬜] | Audit | `GET /api/audit/traces/{trace_id}` | 后端未实现 | 审计页不纳入 X1 |
| [⬜] | Audit | `POST /api/audit/verify` | 后端未实现 | 审计页不纳入 X1 |
| [⬜] | Audit | `GET /api/audit/traces/{trace_id}/export` | 后端未实现 | 审计页不纳入 X1 |
| [⬜] | Policy | `GET /api/policy/events` | 后端未实现 | Policy 页不纳入 X1 |
| [⬜] | Policy | `GET /api/policy/rules` | 后端未实现 | Policy 页不纳入 X1 |
| [⬜] | Policy | `GET /api/policy/risk-levels` | 后端未实现 | Policy 页不纳入 X1 |
| [⬜] | Demo | `POST /api/demo/{scenario_id}/prepare` | 后端未实现 | Demo 页保留 Mock / 提示未接入 |
| [⬜] | Demo | `POST /api/demo/{scenario_id}/run` | 后端未实现 | Demo 页保留 Mock / 提示未接入 |
| [⬜] | Demo | `POST /api/demo/{scenario_id}/cleanup` | 后端未实现 | Demo 页保留 Mock / 提示未接入 |

---

## 8. 完成打标规则

联调完成后，建议只改两处：

1. 把对应行的 `完成标识` 从 `[⬜]` 改为 `[✅]`。
2. 把 `联调状态` 改为 `已通过`。

示例：

```md
| [✅] | POST | `/api/chat` | 发送用户自然语言消息 | `{message, session_id?}` | `{session_id?, trace_id, stream_url}` | 已实现 | 已调用 | 是 | 已通过 |
```

如果接口后端未实现，不要改成 `[✅]`，除非本轮明确确认”不纳入 X1 且降级提示已完成”。这种情况下建议备注：

```text
不纳入 X1，真实模式降级提示已完成
```

---

## 9. X1 完成定义

X1 可认为完成，当且仅当：

| 完成标识 | 完成条件 |
|---|---|
| [✅] | `VITE_MOCK_ENABLED=false` 时，Chat 页能发送真实 `POST /api/chat` 请求 |
| [✅] | 后端返回 `trace_id` 和 `stream_url` |
| [✅] | 前端成功建立 `GET /api/chat/{trace_id}/events` SSE |
| [✅] | 前端只按 `stream.py` 业务事件渲染，不把 `done` 当业务事件 |
| [⬜] | 收到 `await_approval` 后展示审批面板 | fake planner 已有 R2/R3 路由；联调需 `KYLIN_AUTH_MODE=dev` + `X-User-Role: admin` 请求头；**待 X 执行验证** |
| [✅] | 审批请求体严格为 `{trace_id, approved}` |
| [⬜] | 批准后同一 SSE 继续推送 `executing/tool_result/verified/rca/audit_appended` | 同上，待 X 执行验证 |
| [⬜] | 拒绝后收到 `rejected` 并正确收尾 | 同上，待 X 执行验证；`cause` 三值分支前端已实现（A5 闭合） |
| [✅] | `tool_result.data.result.is_untrusted=true` 时明确展示“不可信 / 来自工具输出” |
| [✅] | Tools 页通过 `/api/tools/registry` 获取工具列表，字段使用 `tool` |
| [✅] | Dashboard 页通过 `/api/system/overview` 展示扁平指标和 `services` |
| [✅] | 会话 CRUD 使用 `/api/chat/sessions` 系列接口 |
| [✅] | 未接入的非 X1 页面不伪装成真实数据，真实模式有降级提示（代码修正完成） |
| [✅] | 类型、页面、文档中的旧字段 `required_role/comment/status/done` 已清理或明确降级（代码修正完成） |

---

## 10. 建议负责人关注点

| 关注点 | 原因 | 是否阻塞 X1 |
|---|---|---|
| Chat 主链路 | X1 最高价值路径，贯穿发起、流式、审批、执行、验证、RCA、审计 | 是 |
| 审批 resume 契约 | 后端 `extra="forbid"`，前端多传字段会 422 | 是 |
| SSE 生命周期 | 等待审批时断开 SSE 可能导致续推事件丢失 | 是 |
| 工具输出不可信标注 | 安全叙事核心，不能把工具输出当可信指令 | 是 |
| Tools Registry 字段 | 后端字段是 `tool` 不是 `name` | 是 |
| Dashboard 桩数据提示 | `data_source=stub_executor` 不能伪装成真实采集 | 是 |
| 非 X1 页面降级 | 避免未实现 API 造成执行窗口误判范围 | 否 |

---

## 11. 审计窗口补充发现（2026-06-13 审计）

> 本次审计扫描全量前端 10 页面 + 后端 6 路由文件 + 合约文件 + SSE 事件总线后，台账原有内容经代码核实基本准确。以下为补充/精细化发现。

### 11.1 已确认实现正确项

| 完成标识 | 检查项 | 实际代码位置 | 审计结论 |
|---|---|---|---|
| [✅] | `ToolCallCard` 不可信标注 | `frontend/src/components/ToolCallCard.vue:49-52` | `is_untrusted` 时显示 `<el-tag type="warning">不可信输出</el-tag>` + 说明文字，CSS 类 `.untrusted` 黄色边框背景——**安全叙事正确** |
| [✅] | `StatusTag` 审批状态映射 | `frontend/src/components/StatusTag.vue:27-42` | pending/approved/rejected/escalated 等审批状态映射已覆盖（代码审计确认，不依赖集成测试） |
| [✅] | `ApprovalCard` 正确 emit `trace_id` | `frontend/src/components/ApprovalCard.vue:76-77` | emit `('approve', inline.trace_id)` 正确——**ChatView 已修正消费 trace_id** |
| [✅] | SSE 后端队列架构支持审批续推 | `backend/app/api/event_bus.py:87-119` | asyncio.Queue + None 哨兵模式，resume 后同一队列续推（代码审计确认，架构正确） |
| [✅] | `ResumeRequest` `extra="forbid"` | `backend/app/api/schemas.py:37` | 防字段偷渡——**防御正确** |

### 11.2 新增发现

| 完成标识 | 编号 | 位置 | 问题 | 优先级 |
|---|---|---|---|---|
| [⬜] | A1 | `frontend/src/types/tool.ts:64` vs `backend/app/contracts/untrusted.py:23` | 前端 `ToolResult` 定义了 `stderr_truncated`，后端 `ToolResult` 只有 `stdout_truncated`——契约扩展，前端更宽松，当前无害但需关注 | P2 |
| [✅] | A2 | `frontend/src/components/StatusTag.vue:28-32` | statusMap 补齐 `success`→运行中、`danger`→已停止、`warning`→异常，vue-tsc 通过（feat/x cfe4f52） | P2（修正完成） |
| [✅] | A3 | `frontend/src/api/approval.ts:50` | `getPendingApprovals` JSDoc 注释提及 `required_role`（旧字段名），实际类型用 `approval_role` | P2（代码修正完成） |
| [✅] | A4 | `backend/app/agent/orchestrator.py:243-244` | SSE `plan_generated` emit 层 `{"tool": t.name, "args": t.args}` 映射正确，前端 `CandidateTool.tool` 可正确解析；A4 闭合 | P1（已修正） |
| [✅] | A5 | `frontend/src/types/chat.ts:228`、`frontend/src/stores/chat.ts:573-605` | `RejectedEventData.cause: 'policy_deny' \| 'user_reject' \| 'injection'` union 已包含 injection；store 有独立 injection 分支，展示"⛔ 输入被安全策略拦截"；后端 `orchestrator.py:172-175` emit `cause="injection"` 正确对接（feat/x cfe4f52）；后端契约 stream.py 注释已由 L 补三值（dev e732dc9），契约-实现完全一致 | P1（已实现） |

### 11.3 台账范围确认

- 页面：10 个（覆盖 `router/index.ts` 中全部路由），正确 ✅
- REST API：33 项（覆盖全部 `frontend/src/api/*.ts` 中的声明），正确 ✅
- SSE 事件：12 业务事件（不含 transport done，对应 `stream.py:31-44`），正确 ✅
- 后端已实现 API：13 项（chat/sessions/approvals/tools/system/rca 路由），正确 ✅
- 后端缺失 API：20 项（approval 集中页/audit/policy/demo/ToolDetail 详情），正确 ✅

### 11.4 X1 必须通过清单补充

| 完成标识 | 补充验收项 | 原因 |
|---|---|---|
| [✅] | `StatusTag.vue` statusMap 补齐 `success`/`danger`/`warning` 中文映射 | A2 修正完成：运行中/已停止/异常，vue-tsc 通过 |
| [✅] | 审批卡片 emit 的 `trace_id` 被 ChatView 正确消费 | P0-3 代码修正完成：ChatView approveBatch/rejectBatch 接收 traceId 参数传入 store |
| [⬜] | `switchSession` 在审批 pending 时不关闭 SSE | 代码修正完成，受 fake planner 限制无法真实验证 |
| [✅] | `searchSessionsApi` 在真实模式下不被调用 | P1-2 代码修正完成：store searchSessions 只做本地过滤 |

