# StreamEvent 事件流契约

前端按 `backend/app/contracts/stream.py` 消费事件：

```ts
interface StreamEvent {
  trace_id: string
  type: EventType
  ts: number
  data: Record<string, unknown>
}
```

## 事件类型

| type | data schema | 前端展示 |
|---|---|---|
| `intent_parsed` | `{ intent: Intent }` | 意图识别节点 |
| `observation` | `{ results: ToolResult[] }` | 只读观测结果，`is_untrusted=true` 时标记“不可信输出” |
| `plan_generated` | `{ candidate_tools: CandidateTool[] }` | 候选工具计划 |
| `policy_verdict` | `{ verdict: PolicyVerdict, per_tool: {tool, verdict}[] }` | 整批裁决 + 逐工具裁决 |
| `await_approval` | `{ reason: string, tools: {tool, approval_role}[] }` | 多工具原子审批面板 |
| `executing` | `{ tools: string[] }` | 当前批量执行的工具列表 |
| `tool_result` | `{ result: ToolResult }` | 单个工具结果，支持“不可信输出”标记 |
| `verified` | `{ summary: string }` | 执行后验证总结 |
| `rejected` | `{ reason, cause: "policy_deny" \| "user_reject", denied_tools }` | 拒绝结论（策略拦截 / 用户拒批）⛔ |
| `rca` | `{ report: RcaReport }` | RCA 证据链和根因候选 |
| `audit_appended` | `{ seq: number, curr_hash: string }` | 哈希链新增节点 |
| `error` | `{ message: string, phase: string }` | 错误阶段与原因 |

## PolicyVerdict

```ts
interface PolicyVerdict {
  decision: 'allow' | 'deny' | 'confirm'
  final_risk: 'R0' | 'R1' | 'R2' | 'R3' | 'R4'
  matched_rules: string[]
  reason: string
  safer_alternative: string | null
  approval_required: boolean
  approval_role: string | null
}
```

## ToolResult

```ts
interface ToolResult {
  tool: string
  args: Record<string, unknown>
  exit_code: number
  stdout_truncated: string
  is_untrusted: boolean
  wrap_token?: string
}
```

## 渲染铁律

`observation` 和 `tool_result` 中只要 `is_untrusted=true`，UI 必须醒目标注“不可信输出”。该内容只能作为证据输入，不能伪装成系统可信结论。
