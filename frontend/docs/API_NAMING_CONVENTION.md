# API 字段命名统一规范

本文件说明前端工程当前统一后的 API 字段命名。后端对接时请尽量按本规范返回字段，避免前端再写兼容分支。

| 业务概念 | 统一字段 | 不再使用 | 说明 |
|---|---|---|---|
| 工具名称 | `tool` | `name`、`tool_name` | CandidateTool、ToolResult、ToolCallLog、ToolDefinition 均使用 `tool` |
| 策略规则 ID | `rule_id` | `id` | PolicyRule 使用 `rule_id`；普通 UI 节点或消息本地 ID 仍可使用 `id` |
| 审批所需角色 | `approval_role` | `approval_role` | PolicyVerdict、AwaitApprovalTool、ApprovalItem 统一使用 `approval_role` |
| 审批备注 | `comment` | `reason` 作为备注 | 用户批准、拒绝、转交审批时填写的是 `comment` |
| 业务原因 | `reason` | - | 系统裁决原因、审批原因、错误原因仍使用 `reason` |
| 需要确认裁决 | `confirm` | `approval` | PolicyDecision 只允许 `allow / deny / confirm` |
| Demo 执行动作 | `run` | `start` | Demo 接口使用 `/api/demo/{scenario_id}/run` |

## 示例

### CandidateTool

```json
{
  "tool": "disk.usage",
  "args": { "path": "/" },
  "risk_hint": "R0",
  "justification": "读取根分区使用率"
}
```

### PolicyVerdict

```json
{
  "decision": "confirm",
  "final_risk": "R2",
  "matched_rules": ["LOG001"],
  "reason": "日志轮转属于可逆变更，需要确认",
  "approval_required": true,
  "approval_role": "operator"
}
```

### 审批回传

```json
{
  "trace_id": "t_001",
  "approved": true,
  }
```
