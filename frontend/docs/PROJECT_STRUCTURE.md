# 项目结构说明

```text
frontend/
├── README.md
├── docs/
│   ├── PROJECT_STRUCTURE.md
│   ├── STREAM_EVENT.md
│   └── API_ALIGNMENT.md
└── src/
    ├── api/          后端接口封装
    ├── assets/       静态资源
    ├── components/   可复用业务组件
    ├── layouts/      全局布局与页面标题
    ├── router/       路由配置
    ├── stores/       Pinia 状态管理
    ├── types/        TypeScript 数据契约
    ├── utils/        工具函数与本地缓存
    └── views/        页面级组件
```

## src/api

| 文件 | 说明 |
|---|---|
| `request.ts` | Axios 实例、错误处理、SSE URL 拼接 |
| `chat.ts` | 对话发送、会话 CRUD、SSE 事件流订阅 |
| `approval.ts` | 集中审批和对话页内审批续跑 |
| `audit.ts` | 审计 trace 和哈希链校验 |
| `policy.ts` | 策略规则和安全事件 |
| `rca.ts` | RCA 分析接口 |
| `tools.ts` | 工具注册表和工具调用详情 |
| `system.ts` | 仪表盘系统概览 |
| `demo.ts` | 演示场景接口 |

## src/types

| 文件 | 说明 |
|---|---|
| `chat.ts` | StreamEvent、ChatSession、Intent、事件 data 类型 |
| `policy.ts` | PolicyVerdict、PerToolVerdict、RiskLevel |
| `approval.ts` | ApprovalItem、InlineApproval、审批续跑请求 |
| `tool.ts` | CandidateTool、ToolResult、ToolCallLog |
| `rca.ts` | RcaReport、证据链和根因候选 |
| `audit.ts` | AuditRecord、HashChainVerifyResult |

## src/stores

| 文件 | 说明 |
|---|---|
| `chat.ts` | 多会话、trace 事件、工具结果、审批、RCA、审计链核心状态 |
| `approval.ts` | 审批页列表与详情状态 |
| `audit.ts` | 审计页 trace 与哈希链状态 |

## src/components

| 组件 | 说明 |
|---|---|
| `AgentTimeline.vue` | 渲染 11 种 StreamEvent 的时间轴 |
| `SecurityDecisionCard.vue` | 渲染整批裁决和 per_tool 逐工具裁决 |
| `ApprovalCard.vue` | 集中审批卡片 + 对话页内多工具原子审批 |
| `ToolCallCard.vue` | 工具结果展示，支持“不可信输出”标记 |
| `HashChainViewer.vue` | 哈希链审计节点可视化 |
| `EvidenceTree.vue` | RCA 证据链展示 |
| `RiskTag.vue` | R0-R4 风险标签 |
| `StatusTag.vue` | 状态标签 |

## src/views

`ChatView.vue` 是本次升级重点，其他页面保持 v1 业务逻辑不变。
