import { buildApiUrl, request } from './request'
import {
  connectMockChatStream,
  isMockEnabled,
  mockCreateSession,
  mockDeleteSession,
  mockGetSessionDetail,
  mockGetSessions,
  mockRenameSession,
  mockSearchSessions,
  mockSendMessage,
  type MockChatStreamConnection
} from './mock'
import type { ChatSession, SendMessageRequest, SendMessageResponse, StreamEvent } from '@/types/chat'

/**
 * chat.ts
 *
 * 智能对话与会话管理接口模块。
 *
 * 使用位置：
 * - stores/chat.ts：sendMessage、initSessions、createLocalSession、switchSession 等；
 * - ChatView.vue 不直接调用本文件，而是通过 Store 调用。
 *
 * 主要职责：
 * 1. 发送用户自然语言消息：POST /api/chat；
 * 2. 建立事件流连接：GET /api/chat/{trace_id}/events 或后端返回的 stream_url；
 * 3. 管理左侧多会话：列表、新建、详情、删除、重命名、搜索。
 *
 * Mock 行为：
 * - VITE_MOCK_ENABLED=true：所有接口转到 src/api/mock.ts；
 * - VITE_MOCK_ENABLED=false：请求真实后端；
 * - 页面和 Store 不需要关心当前是真后端还是 Mock。
 */

/**
 * 发送用户自然语言消息。
 *
 * 请求方式：POST /api/chat
 * 使用位置：stores/chat.ts 的 sendMessage(content)
 *
 * 请求体：
 * @param data.session_id 当前会话 ID。后端用它把消息归属到 conversation_session。
 * @param data.message 用户输入的自然语言运维需求，例如“帮我看看磁盘为什么快满了”。
 *
 * 返回体：
 * @returns trace_id 本次请求的全链路追踪 ID。后续 StreamEvent 都用它关联。
 * @returns session_id 后端确认的会话 ID。
 * @returns stream_url 事件流地址。真实模式可为 /api/chat/{trace_id}/events，Mock 模式为 mock://chat/{trace_id}。
 */
export function sendMessage(data: SendMessageRequest) {
  if (isMockEnabled()) return mockSendMessage(data)
  return request.post<SendMessageResponse, SendMessageResponse>('/api/chat', data)
}

/**
 * 获取会话列表。
 *
 * 请求方式：GET /api/chat/sessions
 * 使用位置：stores/chat.ts 的 initSessions()
 * 返回字段：ChatSession[]，用于左侧会话列表。
 */
export function getSessions() {
  if (isMockEnabled()) return mockGetSessions()
  return request.get<ChatSession[], ChatSession[]>('/api/chat/sessions')
}

/**
 * 创建会话。
 *
 * 请求方式：POST /api/chat/sessions
 * 请求体：{ title?: string }
 * 使用位置：ChatView.vue 点击“新建” -> stores/chat.ts createLocalSession()
 */
export function createSession(title?: string) {
  if (isMockEnabled()) return mockCreateSession(title)
  return request.post<ChatSession, ChatSession>('/api/chat/sessions', { title })
}

/**
 * 获取会话详情。
 *
 * 请求方式：GET /api/chat/sessions/{session_id}
 * 使用位置：预留给后端恢复历史消息；当前主要依赖 localStorage 恢复。
 */
export function getSessionDetail(sessionId: string) {
  if (isMockEnabled()) return mockGetSessionDetail(sessionId)
  return request.get(`/api/chat/sessions/${sessionId}`)
}

/**
 * 删除会话。
 *
 * 请求方式：DELETE /api/chat/sessions/{session_id}
 * 使用位置：左侧会话更多菜单 -> 删除。
 */
export function deleteSessionApi(sessionId: string) {
  if (isMockEnabled()) return mockDeleteSession(sessionId)
  return request.delete(`/api/chat/sessions/${sessionId}`)
}

/**
 * 重命名会话。
 *
 * 请求方式：PATCH /api/chat/sessions/{session_id}
 * 请求体：{ title: string }
 * 使用位置：左侧会话更多菜单 -> 重命名。
 */
export function renameSessionApi(sessionId: string, title: string) {
  if (isMockEnabled()) return mockRenameSession(sessionId, title)
  return request.patch<ChatSession, ChatSession>(`/api/chat/sessions/${sessionId}`, { title })
}

/**
 * 搜索会话。
 *
 * 请求方式：GET /api/chat/sessions/search?keyword=xxx
 * 使用位置：左侧会话搜索框。
 * 说明：如果后端未实现，Store getter 会做本地过滤作为兜底。
 */
export function searchSessionsApi(keyword: string) {
  if (isMockEnabled()) return mockSearchSessions(keyword)
  return request.get<ChatSession[], ChatSession[]>('/api/chat/sessions/search', {
    params: { keyword }
  })
}

/**
 * 聊天事件流连接类型。
 *
 * 真实模式返回 EventSource；Mock 模式返回一个只有 close() 方法的对象。
 * Store 只依赖 close() 关闭旧连接，所以可以统一处理。
 */
export type ChatStreamConnection = EventSource | MockChatStreamConnection

/**
 * 建立聊天事件流连接。
 *
 * 真实模式：
 * - 使用 EventSource 连接后端 SSE；
 * - 后端每条消息都是 stream.py 中的 StreamEvent JSON。
 *
 * Mock 模式：
 * - 不访问网络；
 * - connectMockChatStream() 按时间间隔推送 StreamEvent；
 * - 用于前端在后端未完成时开发和演示。
 *
 * @param traceId 本次请求 trace_id。
 * @param streamUrl 后端返回的事件流地址；Mock 模式下为 mock://chat/{traceId}。
 * @param onMessage 收到 StreamEvent 后的回调，Store 会传入 addEvent。
 * @param onError 事件流异常回调。
 */
export function connectChatStream(
  traceId: string,
  streamUrl: string | undefined,
  onMessage: (event: StreamEvent) => void,
  onError?: (error: Event) => void
): ChatStreamConnection {
  if (isMockEnabled() || streamUrl?.startsWith('mock://')) {
    return connectMockChatStream(traceId, onMessage, onError)
  }

  const url = buildApiUrl(streamUrl || `/api/chat/${traceId}/events`)
  const source = new EventSource(url)

  source.onmessage = message => {
    if (!message.data) return
    try {
      onMessage(JSON.parse(message.data) as StreamEvent)
    } catch (error) {
      console.error('SSE message parse failed', error, message.data)
    }
  }

  source.onerror = error => {
    onError?.(error)
  }

  return source
}
