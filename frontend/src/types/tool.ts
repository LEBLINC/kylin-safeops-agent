import type { RiskLevel } from './policy'

/**
 * tool.ts
 *
 * MCP 工具、候选工具、工具调用结果相关类型。
 *
 * 命名统一原则：
 * - 工具名称统一使用 tool；
 * - 不再在前端数据结构中混用 name / tool_name；
 * - 如果后端旧接口仍返回 name/tool_name，应在 API 适配层转换成 tool 后再进入页面和 Store。
 */

/**
 * ToolDefinition
 *
 * MCP 工具注册表中的工具定义。
 * 来源接口：GET /api/tools/registry。
 */
export interface ToolDefinition {
  /** 工具唯一名称，例如 disk.usage / service.restart / log.compress_rotate。 */
  tool: string
  /** 工具说明，展示给用户和评委看。 */
  description: string
  /** 工具默认风险等级，真正执行前还会经过 PolicyVerdict 再裁决。 */
  risk: RiskLevel
  /** 工具输入参数 JSON Schema，用于工具详情页展示和后端参数校验说明。 */
  input_schema?: Record<string, unknown>
}

/**
 * CandidateTool
 *
 * LLM/Planner 在 plan_generated 事件中提出的候选工具。
 * 来源事件：plan_generated.data.candidate_tools[]。
 */
export interface CandidateTool {
  /** 工具名称，统一使用 tool。 */
  tool: string
  /** 工具入参。必须是结构化参数，不能是裸 shell 命令。 */
  args: Record<string, unknown>
  /** 规划阶段的粗略风险提示，最终风险以后端 PolicyVerdict.final_risk 为准。 */
  risk_hint?: string
  /** 为什么选择这个工具。只展示摘要，不展示模型私有推理链。 */
  justification?: string
}

/**
 * ToolResult
 *
 * 工具调用结果。
 * 来源事件：observation.data.results[] / tool_result.data.result。
 */
export interface ToolResult {
  /** 工具名称，统一使用 tool。 */
  tool: string
  /** 工具实际执行参数。 */
  args?: Record<string, unknown>
  /** 进程退出码，0 通常表示成功。 */
  exit_code?: number
  /** 标准输出的截断文本。 */
  stdout_truncated?: string
  /** 标准错误的截断文本。 */
  stderr_truncated?: string | null
  /** 是否不可信。来自日志、命令输出、外部上下文的内容应为 true。 */
  is_untrusted?: boolean
  /** 不可信上下文包装标识。 */
  wrap_token?: string | null
  /** 工具耗时，单位毫秒。 */
  duration_ms?: number
  /** 调用状态。 */
  status?: 'pending' | 'running' | 'success' | 'failed'
  /** 工具调用 ID，用于详情页跳转。 */
  call_id?: string
  /** 兼容页面展示的结构化输出；真实后端建议优先使用 stdout_truncated。 */
  output?: unknown
  /** 错误信息。 */
  error?: string
}

/**
 * ToolCallLog
 *
 * 审计页或工具详情页使用的工具调用日志。
 */
export interface ToolCallLog {
  /** 工具调用 ID。 */
  call_id: string
  /** 对应 trace_id。 */
  trace_id: string
  /** 工具名称，统一使用 tool。 */
  tool: string
  /** 工具入参。 */
  args: Record<string, unknown>
  /** 工具返回结果。 */
  result?: unknown
  /** 调用状态。 */
  status: 'pending' | 'running' | 'success' | 'failed'
  /** 调用耗时，单位毫秒。 */
  duration_ms?: number
  /** 本次工具调用的风险等级。 */
  risk_level?: RiskLevel
  /** 创建时间。 */
  created_at?: string
}
