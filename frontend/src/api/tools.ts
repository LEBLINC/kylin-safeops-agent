import { request } from './request'
import type { ToolCallLog, ToolDefinition } from '@/types/tool'

/**
 * tools.ts
 *
 * MCP 工具相关接口模块。
 *
 * 作用：
 * 1. 查询工具注册表；
 * 2. 查询某次工具调用详情；
 * 3. 手动调用工具，供调试或演示使用。
 *
 * 与 stream.py 的关系：
 * - stream.py 中 observation/tool_result 会携带 ToolResult；
 * - 工具注册表 ToolDefinition、工具详情 ToolCallLog 是 REST 接口数据，不由 stream.py 直接规定。
 */

/**
 * 获取 MCP 工具注册表。
 *
 * 使用位置：
 * - src/views/ToolsView.vue
 *
 * 请求方式：
 * - GET /api/tools/registry
 *
 * 请求参数：
 * - 无
 *
 * 返回数据：
 * - ToolDefinition[]
 * - 每个工具包含 tool、description、risk、input_schema、是否需要审批等。
 */
export function getToolRegistry() {
  return request.get<ToolDefinition[], ToolDefinition[]>('/api/tools/registry')
}

/**
 * 获取某次工具调用详情。
 *
 * 使用位置：
 * - src/views/ToolDetailView.vue
 *
 * 请求方式：
 * - GET /api/tools/calls/{call_id}
 *
 * 请求参数：
 * @param callId 工具调用 ID。注意这不是 trace_id；一个 trace 里可能有多个工具调用。
 *
 * 返回数据：
 * - ToolCallLog
 * - 包含工具名、参数、结果、状态、耗时、风险等级等。
 */
export function getToolCallDetail(callId: string) {
  return request.get<ToolCallLog, ToolCallLog>(`/api/tools/calls/${callId}`)
}

/** 按工具名查历史调用列表。 */
export function listToolCalls(tool: string, limit = 10) {
  return request.get('/api/tools/calls', { params: { tool, limit } })
}

/**
 * 手动调用某个工具。
 *
 * 使用位置：
 * - 后续工具调试页面；
 * - DemoView.vue 可以用它触发只读诊断工具。
 *
 * 请求方式：
 * - POST /api/tools/call
 *
 * 请求体：
 * @param tool 工具名，例如 disk.usage、service.status。
 * @param args 工具参数对象，必须符合工具注册表里的 input_schema。
 *
 * 安全说明：
 * - 真实后端必须对 tool/args 再做策略校验；
 * - 前端不能因为页面隐藏按钮就认为安全。
 */
export function callTool(tool: string, args: Record<string, unknown>) {
  return request.post('/api/tools/call', { tool, args })
}
