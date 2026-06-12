import type { CandidateTool, ToolResult } from './tool'
import type { InlineApproval } from './approval'
import type { PerToolVerdict, PolicyVerdict, RiskLevel } from './policy'
import type { RcaReport } from './rca'

/**
 * EventType
 *
 * 前端事件流的事件类型枚举。
 * 来源：backend/app/contracts/stream.py。
 *
 * 说明：
 * - 这里不能随便新增事件类型；
 * - 如果后端要新增 assistant_delta / token_delta 等真正 token 流事件，必须先走 contract 对齐；
 * - 当前聊天“打字机效果”是在收到 verified.summary 后由前端逐字渲染，不是后端逐 token 推送。
 */
export type EventType =
  | 'intent_parsed'
  | 'observation'
  | 'plan_generated'
  | 'policy_verdict'
  | 'await_approval'
  | 'executing'
  | 'tool_result'
  | 'verified'
  | 'rca'
  | 'audit_appended'
  | 'done'
  | 'error'

/**
 * StreamEvent
 *
 * 后端通过 SSE/WS 推送给前端的统一事件外壳。
 * 来源：backend/app/contracts/stream.py。
 *
 * 使用位置：
 * - src/api/chat.ts：connectChatStream() 解析 SSE 消息；
 * - src/api/mock.ts：Mock 模式下模拟推送 11 种事件；
 * - src/stores/chat.ts：addEvent() 消费事件并拆分到页面状态；
 * - src/components/AgentTimeline.vue：把事件转换成执行时间轴。
 */
export interface StreamEvent {
  /** 单次用户请求的全链路追踪 ID。一次请求的意图、工具、策略、审批、审计都用同一个 trace_id 串起来。 */
  trace_id: string
  /** 事件类型，只能是 stream.py 中规定的 11 种。 */
  type: EventType
  /** 事件发生时间，epoch 秒。前端用于时间轴排序和显示。 */
  ts: number
  /**
   * 事件载荷。
   * stream.py 当前只把 data 定义为 dict，没有强类型展开。
   * 前端需要根据 type 分别读取：
   * - policy_verdict：data.verdict / data.per_tool
   * - tool_result：data.result
   * - await_approval：data.reason / data.tools
   * - rca：data.report
   */
  data: Record<string, unknown>
}

/**
 * Intent
 *
 * LLM 意图识别结果。
 * 来源：intent_parsed 事件的 data.intent。
 * stream.py 只写了 intent_parsed -> {"intent": Intent}，没有在代码里展开字段；
 * 以下字段来自接口对齐文档与前端展示需要。
 */
export interface Intent {
  /** 意图名称，例如 disk_full_diagnosis / service_restart_check。 */
  intent?: string
  /** 置信度，0~1。 */
  confidence?: number
  /** 是否需要先调用只读工具采集环境证据。 */
  need_observation?: boolean
  /** LLM 认为可能需要调用的候选工具。 */
  candidate_tools?: CandidateTool[]
  /** 低/中/高等粗粒度风险提示，真正裁决以后端 PolicyVerdict 为准。 */
  risk_hint?: string
  /** 意图判断理由，用于前端时间轴摘要，不展示私有推理链。 */
  justification?: string
  /** 可选摘要，兼容后端简化输出。 */
  summary?: string
}

/**
 * ChatSession
 *
 * 左侧会话列表项。
 * 注意：该结构不是 stream.py 规定的，它属于 REST 会话接口和前端多会话管理需要。
 */
export interface ChatSession {
  /** 会话 ID，推荐后端统一使用 session_id。 */
  session_id: string
  /** 兼容 v1 旧字段 id，后续可逐步移除。 */
  id?: string
  /** 会话标题，左侧列表展示，也用于搜索。 */
  title: string
  /** 会话创建时间，ISO 字符串。 */
  created_at?: string
  /** 会话最近更新时间，用于排序和展示。 */
  updated_at?: string
  /** 最近一条消息摘要。 */
  last_message?: string
  /** 最近一次请求的 trace_id，切换会话时用于恢复右侧执行链路。 */
  last_trace_id?: string
  /** 最近一次请求的最高风险等级，用于左侧风险标签。 */
  risk_level?: RiskLevel
  /** 当前会话里待审批批次数量，用于左侧提醒。 */
  pending_approval_count?: number
}

/**
 * ChatMessage
 *
 * 中间聊天窗口展示的消息。
 * 来源：
 * - 用户点击发送时前端创建 role=user 的消息；
 * - 收到 verified.summary 后前端创建 role=assistant 的打字机消息；
 * - 收到 await_approval 后前端创建 role=system 且带 approval 的内联审批消息。
 */
export interface ChatMessage {
  /** 前端本地消息 ID，用于 v-for key。 */
  id: string
  /** 消息角色：用户、AI 助手、系统提醒。 */
  role: 'user' | 'assistant' | 'system'
  /** 文本内容。审批消息也会有一段说明文字，但按钮和工具列表来自 approval 字段。 */
  content: string
  /** 消息创建时间，ISO 字符串。 */
  created_at: string
  /** 关联的 trace_id，用于点击消息时可定位右侧执行链路。 */
  trace_id?: string
  /** 消息状态。streaming 表示打字机效果正在输出。 */
  status?: 'sending' | 'streaming' | 'done' | 'error'
  /** 如果这条消息是“对话内审批卡片”，这里保存审批数据。 */
  approval?: InlineApproval
}

/** POST /api/chat 的请求体。 */
export interface SendMessageRequest {
  /** 当前会话 ID。后端用它把消息归属到会话。 */
  session_id?: string
  /** 用户输入的自然语言运维需求。 */
  message: string
}

/** POST /api/chat 的返回体。 */
export interface SendMessageResponse {
  /** 后端确认的会话 ID。 */
  session_id?: string
  /** 本次请求 trace_id，后续事件流都通过它关联。 */
  trace_id: string
  /** SSE/WS 地址。Mock 模式下形如 mock://chat/{traceId}。 */
  stream_url?: string
}

/** plan_generated 事件 data 结构。 */
export interface AgentPlanData {
  candidate_tools?: CandidateTool[]
}

/** policy_verdict 事件 data 结构。 */
export interface PolicyVerdictData {
  verdict?: PolicyVerdict
  per_tool?: PerToolVerdict[]
}

/** observation 事件 data 结构。 */
export interface ObservationData {
  results?: ToolResult[]
}

/** tool_result 事件 data 结构。 */
export interface ToolResultData {
  result?: ToolResult
}

/** await_approval.data.tools[] 中的一项。 */
export interface AwaitApprovalTool {
  /** 待审批工具名，例如 service.restart / log.compress_rotate。 */
  tool: string
  /** 该工具要求的最低审批角色；为空表示无需特定角色。 */
  approval_role?: string | null
}

/** await_approval 事件 data 结构。 */
export interface AwaitApprovalData {
  /** 为什么需要审批。 */
  reason?: string
  /** 本批原子计划中所有待确认工具。批准/拒绝对整批生效。 */
  tools?: AwaitApprovalTool[]
}

/** executing 事件 data 结构。 */
export interface ExecutingData {
  /** 本批正在执行的工具名列表。 */
  tools?: string[]
}

/** rca 事件 data 结构。 */
export interface RcaEventData {
  /** RCA 报告。stream.py 只规定 report 是 dict，具体结构由前端/RCA 实现侧约定。 */
  report?: RcaReport
}

/** audit_appended 事件 data 结构。 */
export interface AuditAppendedData {
  /** 审计链序号。 */
  seq: number
  /** 当前节点 hash。 */
  curr_hash: string
}

/** error 事件 data 结构。 */
export interface StreamErrorData {
  /** 错误信息。 */
  message: string
  /** 错误发生阶段，例如 policy / executing / rca。 */
  phase: string
}
