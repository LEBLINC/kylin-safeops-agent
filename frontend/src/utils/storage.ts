import type { InlineApproval } from '@/types/approval'
import type { ChatMessage, ChatSession, StreamEvent } from '@/types/chat'
import type { AuditAppendedData } from '@/types/chat'
import type { PolicyVerdict } from '@/types/policy'
import type { RcaReport } from '@/types/rca'
import type { ToolResult } from '@/types/tool'

/**
 * storage.ts
 *
 * 前端本地缓存工具。
 *
 * 作用：
 * - 把多会话聊天状态保存到 localStorage；
 * - 刷新浏览器后恢复当前会话、消息、事件流、工具结果、审批、RCA、审计链；
 * - 让前端在后端会话接口尚未完成时也能稳定演示。
 *
 * 重要说明：
 * - localStorage 只是前端轻量缓存，不是正式数据库；
 * - 正式审计、审批、trace、工具调用记录必须以后端 SQLite/openGauss/JSONL 为准；
 * - 这里保存的数据可以被用户浏览器清理或篡改，因此不能作为可信审计证据。
 */
const STORAGE_KEY = 'kylin-safeops-chat-state-v1'

/**
 * ChatPersistState
 *
 * 需要持久化到浏览器 localStorage 的聊天状态。
 *
 * 字段说明：
 * @field sessions 会话列表，用于左侧会话栏恢复。
 * @field currentSessionId 当前选中的会话 ID，用于刷新后回到上次会话。
 * @field messagesBySession 每个会话自己的聊天消息，避免多会话消息串在一起。
 * @field traceIdsBySession 每个会话产生过哪些 trace，便于切换会话时找回执行链路。
 * @field activeTraceIdBySession 每个会话当前正在展示的 trace。
 * @field eventsByTrace 每个 trace 的 StreamEvent 列表，是右侧执行链路的数据来源。
 * @field toolResultsByTrace 每个 trace 的工具结果列表，是 ToolCallCard 的数据来源。
 * @field policyVerdictByTrace 每个 trace 的整批安全裁决，是 SecurityDecisionCard 的数据来源。
 * @field approvalByTrace 每个 trace 当前的对话内审批信息，是聊天区审批卡片的数据来源。
 * @field auditNodesByTrace 每个 trace 实时追加的审计 hash 节点，是 HashChainViewer 的数据来源。
 * @field rcaReportByTrace 每个 trace 的 RCA 报告，是 EvidenceTree/RCA 区域的数据来源。
 */
export interface ChatPersistState {
  sessions: ChatSession[]
  currentSessionId: string
  messagesBySession: Record<string, ChatMessage[]>
  traceIdsBySession: Record<string, string[]>
  activeTraceIdBySession: Record<string, string>
  eventsByTrace: Record<string, StreamEvent[]>
  toolResultsByTrace: Record<string, ToolResult[]>
  policyVerdictByTrace: Record<string, PolicyVerdict | null>
  approvalByTrace: Record<string, InlineApproval | null>
  auditNodesByTrace: Record<string, AuditAppendedData[]>
  rcaReportByTrace: Record<string, RcaReport | null>
}

/**
 * 从 localStorage 读取聊天状态。
 *
 * 使用位置：
 * - stores/chat.ts 的 initSessions()。
 *
 * 返回：
 * - 成功时返回部分 ChatPersistState；
 * - 如果没有缓存、JSON 解析失败、浏览器禁用 localStorage，则返回 null。
 *
 * 设计原因：
 * - 读取缓存失败不应该阻塞页面启动；
 * - 因此捕获错误后只打印 warning，并让 Store 创建默认会话。
 */
export function loadChatState(): Partial<ChatPersistState> | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Partial<ChatPersistState>) : null
  } catch (error) {
    console.warn('读取本地聊天状态失败：', error)
    return null
  }
}

/**
 * 保存聊天状态到 localStorage。
 *
 * 使用位置：
 * - stores/chat.ts 每次会话、消息、事件流变化后调用。
 *
 * 入参：
 * @param state 完整的聊天持久化状态。
 *
 * 注意：
 * - 这里会把状态 JSON.stringify 后整体写入；
 * - 如果后续数据量变大，可以改成只保存会话摘要，详细 trace 交给后端。
 */
export function saveChatState(state: ChatPersistState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch (error) {
    console.warn('保存本地聊天状态失败：', error)
  }
}

/**
 * 清理全部本地聊天缓存。
 *
 * 使用位置：
 * - 后续 SettingsView.vue 可增加“清空本地缓存”按钮；
 * - 调试多会话状态异常时也可手动调用。
 *
 * 说明：
 * - 只删除浏览器本地缓存，不影响后端数据库中的会话、审计、审批数据。
 */
export function clearChatState() {
  localStorage.removeItem(STORAGE_KEY)
}
