# 与 L 后端接口对齐建议

## 0. 字段命名统一规范

本版本已统一前端 API 字段命名：

| 业务概念 | 统一字段 | 不再使用 |
|---|---|---|
| 工具名称 | `tool` | `name`、`tool_name` |
| 策略规则 ID | `rule_id` | `id` |
| 审批所需角色 | `required_role` | `approval_role` |
| 审批备注 | `comment` | 使用 `reason` 表示备注 |
| 需要确认裁决 | `confirm` | `approval` |
| Demo 执行动作 | `run` | `start` |


## 1. 连接层

建议采用：

```text
SSE + REST
```

- SSE：后端向前端推送 11 种 StreamEvent。
- REST：前端向后端回传审批结果。

这样可以兼容 v1 已有 `EventSource` 实现，审批也更符合一次性 HTTP 动作。

## 2. 对话接口

```http
POST /api/chat
```

请求：

```json
{
  "session_id": "s_001",
  "message": "帮我看看磁盘为什么快满了"
}
```

返回：

```json
{
  "session_id": "s_001",
  "trace_id": "t_001",
  "stream_url": "/api/chat/t_001/events"
}
```

SSE：

```http
GET /api/chat/{trace_id}/events
```

## 3. 会话接口

```http
GET    /api/chat/sessions
POST   /api/chat/sessions
GET    /api/chat/sessions/{session_id}
PATCH  /api/chat/sessions/{session_id}
DELETE /api/chat/sessions/{session_id}
GET    /api/chat/sessions/search?keyword=xxx
```

后端未接入时，前端使用 localStorage 兜底。

## 4. 审批续跑接口

建议 L 后端落地：

```http
POST /api/approvals/resume
```

批准：

```json
{
  "trace_id": "t_001",
  "approved": true,
  "comment": "确认执行本批计划"
}
```

拒绝：

```json
{
  "trace_id": "t_001",
  "approved": false,
  "comment": "风险较高，拒绝执行"
}
```

返回：

```json
{
  "trace_id": "t_001",
  "status": "resumed"
}
```

## 5. RCA report 建议结构

```ts
interface RcaReport {
  problem_type: 'disk_full' | 'zombie_process' | 'io_high' | 'config_drift' | 'service_abnormal' | 'unknown'
  summary: string
  root_cause_candidates: Array<{
    cause: string
    confidence: number
    evidence_refs: string[]
    evidence: string[]
  }>
  evidence_chain: Array<{
    id: string
    source_tool: string
    title: string
    detail: string
    is_untrusted: boolean
  }>
  safe_actions: string[]
  dangerous_actions_rejected: Array<{
    action: string
    reason: string
    rule_id?: string
  }>
  recommended_next_steps: string[]
}
```

## API 层 Mock 更新说明

本版本约定：前端页面不直接生成 Mock 业务数据，统一由 `src/api/mock.ts` 模拟后端返回。

### 智能对话 Mock 流程

| 步骤 | 文件 | 说明 |
|---|---|---|
| 1 | `ChatView.vue` | 用户点击“发送” |
| 2 | `stores/chat.ts` | 调用 `sendMessageApi({ session_id, message })` |
| 3 | `api/chat.ts` | 判断 `VITE_MOCK_ENABLED` |
| 4 | `api/mock.ts` | 返回模拟 `trace_id` 和 `mock://chat/{trace_id}` |
| 5 | `stores/chat.ts` | 调用 `connectChatStream()` |
| 6 | `api/mock.ts` | 按时间顺序推送 `StreamEvent` |
| 7 | `stores/chat.ts` | `addEvent()` 根据事件类型写入不同 trace 状态 |

### 审批 Mock 流程

| 步骤 | 文件 | 说明 |
|---|---|---|
| 1 | `ApprovalCard.vue` | 用户点击“批准整批执行”或“拒绝整批执行” |
| 2 | `stores/chat.ts` | 调用 `resumeApproval({ trace_id, approved, comment })` |
| 3 | `api/approval.ts` | Mock 模式转发给 `mockResumeApproval()` |
| 4 | `api/mock.ts` | 继续推动同一个 mock stream，发出 `executing/tool_result/verified/rca/audit_appended` |

### 设计目的

这样做后，Mock 和真实后端的差异只存在于 API 层；页面、store、组件都按照同一套数据流工作，便于后续联调。

## v1.3 补充：对话内审批与打字机效果

### 对话内审批

审批操作不放在右侧执行详情区，而是作为 system 消息出现在中间聊天区。

- 权限足够：显示“批准整批执行 / 拒绝整批执行”。
- 权限不足：显示“申请转管理员审批”。
- 右侧只显示执行链路、安全裁决、工具结果、RCA、审计链。

新增建议接口：

```http
POST /api/approvals/escalate
```

请求体：

```json
{
  "trace_id": "t_001",
  "comment": "当前用户权限不足，申请管理员审批",
  "tools": [{ "tool": "service.restart", "required_role": "Admin" }]
}
```

### 打字机效果

当前 stream.py 没有 token 级事件。前端在收到 `verified` 事件后，读取 `data.summary`，并在聊天窗口中逐字显示。

如果后端后续新增 `assistant_delta`，需要先走 contract 对齐。

### RCA API Mock

RCA 页面已改为：

```text
RcaView.vue → api/rca.ts → api/mock.ts
```

Mock 支持 `disk_full`、`zombie_process`、`io_high`、`config_drift` 四类场景。
