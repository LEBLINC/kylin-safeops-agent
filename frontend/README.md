# Kylin SafeOps Agent Frontend

面向麒麟操作系统的安全智能运维 Agent 前端工程。

本版本基于 v1 工程迭代，重点完成：

- API 层 Mock：页面点击发送后仍然走 `api/chat.ts`，由 API 层决定真实后端或 Mock。
- 11 种 StreamEvent：按 `backend/app/contracts/stream.py` 对齐。
- 多会话管理：新建、切换、删除、重命名、搜索。
- 对话内审批：审批卡片显示在中间聊天区，不放在右侧。
- 权限不足转审批：当前角色不够时显示“申请转管理员审批”。
- 打字机效果：收到 `verified.summary` 后前端逐字显示 AI 回复。
- RCA API Mock：独立 `RcaView.vue` 通过 `api/rca.ts -> api/mock.ts` 获取数据。
- 详细中文注释：API、Type、Store、Vue 页面、核心组件均补充了用途、字段、数据流说明。
- 三栏独立滚动：左侧会话、中间对话、右侧链路各自滚动。

## 运行方式

```bash
npm install
npm run dev
```

生产构建：

```bash
npm run build
```

> 前端在 x86 开发机上构建静态包，再拷贝到麒麟 / LoongArch 环境部署，不建议在 LoongArch 上跑 npm build。

## 环境变量

开发环境 `.env.development`：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_PROXY_TARGET=http://127.0.0.1:8000
VITE_STREAM_MODE=sse
VITE_CURRENT_USER_ROLE=Admin
VITE_MOCK_ENABLED=true
```

字段说明：

| 字段 | 含义 |
|---|---|
| `VITE_API_BASE_URL` | 真实后端 API 地址 |
| `VITE_PROXY_TARGET` | Vite 代理目标 |
| `VITE_STREAM_MODE` | 当前建议使用 `sse` |
| `VITE_CURRENT_USER_ROLE` | 当前前端模拟角色，Viewer / Operator / Admin / Auditor |
| `VITE_MOCK_ENABLED` | `true` 时走 API 层 Mock，`false` 时请求真实后端 |

## 智能对话数据流

```text
用户点击发送
→ ChatView.submit()
→ stores/chat.ts sendMessage()
→ api/chat.ts sendMessage()
→ 真实后端 /api/chat 或 api/mock.ts
→ 返回 trace_id / stream_url
→ connectChatStream()
→ 持续接收 StreamEvent
→ stores/chat.ts addEvent()
→ 页面实时刷新
```

## 对话内审批数据流

```text
收到 await_approval 事件
→ stores/chat.ts 生成 InlineApproval
→ 中间聊天区插入系统审批消息
→ 权限足够：批准整批执行 / 拒绝整批执行
→ 权限不足：申请转管理员审批
```

审批接口建议：

```http
POST /api/approvals/resume
POST /api/approvals/escalate
```

## 打字机效果说明

当前 `stream.py` 没有定义 token 级事件，例如 `assistant_delta`。
因此本前端的打字机效果是：

```text
收到 verified 事件
→ 读取 data.summary
→ 前端逐字追加到 assistant 消息
```

如果后端后续新增 token 级事件，需要先走 contract 对齐，再改前端事件处理。

## RCA 数据流

独立 RCA 页面：

```text
RcaView.vue
→ api/rca.ts startRcaAnalysis()
→ api/mock.ts mockStartRcaAnalysis() 或真实后端 POST /api/rca/analyze
→ api/rca.ts getRcaResult()
→ api/mock.ts mockGetRcaResult() 或真实后端 GET /api/rca/{trace_id}
```

支持演示场景：

- `disk_full`：磁盘满
- `zombie_process`：僵尸进程
- `io_high`：I/O 异常
- `config_drift`：配置漂移


## API 字段命名统一规范

本版本对前端 API 数据结构做了统一，避免同一业务概念出现多个字段名：

| 业务概念 | 统一字段 | 不再使用 |
|---|---|---|
| 工具名称 | `tool` | `name`、`tool_name` |
| 策略规则 ID | `rule_id` | `id` |
| 审批所需角色 | `required_role` | `approval_role` |
| 审批备注 | `comment` | 使用 `reason` 表示备注 |
| 需要确认裁决 | `confirm` | `approval` |
| Demo 执行动作 | `run` | `start` |

说明：`reason` 仍然保留为“系统给出的原因/裁决原因/审批原因”，但用户在批准、拒绝、转交审批时填写的备注统一叫 `comment`。

## 目录结构

```text
src/api/          后端接口封装与 API 层 Mock
src/types/        TypeScript 类型定义，包含字段含义注释
src/stores/       Pinia 状态管理，多会话、trace、审批、打字机
src/views/        页面级组件
src/components/   业务组件：时间轴、裁决卡、工具结果、审批卡、哈希链、证据树
src/utils/        格式化、本地缓存、风险等级工具
src/layouts/      全局布局和页面标题
```

## 关键文件

| 文件 | 作用 |
|---|---|
| `src/api/chat.ts` | 发送消息、会话 CRUD、连接 SSE/Mock Stream |
| `src/api/mock.ts` | 统一 Mock 会话、事件流、审批续跑、RCA 报告 |
| `src/api/approval.ts` | 审批列表、审批续跑、转管理员审批 |
| `src/api/rca.ts` | RCA 分析接口 |
| `src/stores/chat.ts` | 智能对话核心状态管理 |
| `src/views/ChatView.vue` | 三栏布局、对话、内联审批、打字机 |
| `src/views/RcaView.vue` | 独立 RCA 页面 |
| `src/components/ApprovalCard.vue` | 对话内审批和审批页卡片 |
