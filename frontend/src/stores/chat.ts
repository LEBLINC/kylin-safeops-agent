import { request } from '@/api/request'
import { defineStore } from 'pinia'
import {
  connectChatStream,
  createSession,
  deleteSessionApi,
  getSessions,
  renameSessionApi,
  sendMessage as sendMessageApi,
  type ChatStreamConnection
} from '@/api/chat'
import { escalateApproval, resumeApproval } from '@/api/approval'
import type { InlineApproval } from '@/types/approval'
import type { UserRole } from '@/types/policy'
import type { AuditAppendedData, ChatMessage, ChatSession, StreamEvent } from '@/types/chat'
import { isMockEnabled } from '@/api/mock'
import type { PolicyVerdict } from '@/types/policy'
import type { RcaReport } from '@/types/rca'
import type { ToolResult } from '@/types/tool'
import { loadChatState, saveChatState } from '@/utils/storage'

/** 生成前端本地使用的唯一 ID，用于消息、会话等临时对象。 */
function uid(prefix = 'id') {
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

/** 返回当前时间 ISO 字符串，统一用于消息和会话时间字段。 */
function nowIso() {
  return new Date().toISOString()
}

/** 根据剩余长度和标点控制打字机节奏：长句更快，遇到停顿标点稍作停留。 */
function typingStep(text: string, index: number) {
  const current = text[index] || ''
  if (/[,，、]/.test(current)) return { step: 2, delay: 70 }
  if (/[。！？；：.!?;:]/.test(current)) return { step: 2, delay: 150 }
  if (/\s/.test(current)) return { step: 3, delay: 26 }
  const remaining = Math.max(0, text.length - index)
  if (remaining > 120) return { step: 7, delay: 18 }
  if (remaining > 80) return { step: 6, delay: 20 }
  if (remaining > 48) return { step: 4, delay: 24 }
  return { step: 2, delay: 28 }
}

/**
 * 兼容 v1 的 id 字段和新会话契约的 session_id 字段。
 * 后续如果后端统一只返回 session_id，这个函数仍然可以保留，避免旧缓存报错。
 */
function sessionIdOf(session: ChatSession) {
  return session.session_id || session.id || 'local'
}

/**
 * 将后端 / Mock / localStorage 中的会话统一成前端可安全使用的结构。
 *
 * 为什么需要 normalize：
 * 1. 后端接口字段仍在对齐，可能只返回 session_id/title；
 * 2. localStorage 里可能保存旧版本字段；
 * 3. 页面渲染不应该到处写空值判断。
 */
function normalizeSession(session: Partial<ChatSession>): ChatSession {
  const id = session.session_id || session.id || uid('session')
  return {
    session_id: id,
    id,
    title: session.title || '新会话',
    created_at: session.created_at || nowIso(),
    updated_at: session.updated_at || nowIso(),
    last_message: session.last_message || '',
    last_trace_id: session.last_trace_id,
    risk_level: session.risk_level,
    pending_approval_count: session.pending_approval_count || 0
  }
}

/** 页面权限判断使用的角色等级。数字越大权限越高。 */
export const roleRank: Record<string, number> = { viewer: 1, auditor: 1, operator: 2, admin: 3 }

/** 判断 currentRole 是否满足 requiredRole。 */
export function canRoleApprove(currentRole: string, requiredRole?: string | null) {
  if (!requiredRole) return true
  return (roleRank[currentRole] || 0) >= (roleRank[requiredRole] || 3)
}

/**
 * 计算一批待审批工具中需要的最高角色。
 *
 * 多工具原子计划语义：
 * - await_approval.data.tools 可能包含多个工具；
 * - 用户批准/拒绝是对整批计划生效；
 * - 如果其中一个工具需要 Admin，那么整批都必须由 Admin 批准。
 */
function requiredRoleOf(tools: InlineApproval['tools']): InlineApproval['approval_role'] {
  let role: UserRole | null = null
  let rank = 0
  for (const item of tools) {
    const currentRole = (item.approval_role || null) as UserRole | null
    const currentRank = currentRole ? roleRank[currentRole] || 3 : 0
    if (currentRank > rank) {
      role = currentRole
      rank = currentRank
    }
  }
  return role
}


/** Debounce timer for throttled localStorage writes (avoid O(n^2) per SSE event). */
let _persistTimer: ReturnType<typeof setTimeout> | null = null

export const useChatStore = defineStore('chat', {
  state: () => ({
    /** 左侧会话列表。数据来源：localStorage、/api/chat/sessions 或 api/mock.ts。 */
    sessions: [] as ChatSession[],
    /** 当前选中的会话 ID。刷新后会从 localStorage 恢复。 */
    currentSessionId: 'local',
    /** 左侧搜索框关键字。 */
    searchKeyword: '',

    /**
     * 多会话消息隔离。
     * messagesBySession[session_id] 保存该会话的消息，避免 A 会话消息串到 B 会话。
     */
    messagesBySession: {} as Record<string, ChatMessage[]>,
    /** 每个会话产生过的 trace_id 列表。 */
    traceIdsBySession: {} as Record<string, string[]>,
    /** 每个会话当前展示的 trace_id。 */
    activeTraceIdBySession: {} as Record<string, string>,

    /**
     * trace 级数据隔离。
     * 一次用户请求对应一个 trace_id，事件流、工具结果、审批、RCA、审计链都按 trace_id 保存。
     */
    eventsByTrace: {} as Record<string, StreamEvent[]>,
    toolResultsByTrace: {} as Record<string, ToolResult[]>,
    policyVerdictByTrace: {} as Record<string, PolicyVerdict | null>,
    approvalByTrace: {} as Record<string, InlineApproval | null>,
    auditNodesByTrace: {} as Record<string, AuditAppendedData[]>,
    rcaReportByTrace: {} as Record<string, RcaReport | null>,
    /** RCA LLM 自然语言根因摘要（可选，后端 rca 事件 llm_summary 字段；无摘要时为 null）。 */
    rcaLlmSummaryByTrace: {} as Record<string, string | null>,

    /** 当前 SSE/Mock stream 连接。切换会话时关闭，防止旧 trace 继续写入。 */
    stream: null as ChatStreamConnection | null,
    /** 页面发送中 / 事件流未结束时使用。 */
    loading: false,
    /** 当前用户角色。暂时从环境变量读取，后续可接登录态。 */
    currentUserRole: (import.meta.env.VITE_CURRENT_USER_ROLE || 'viewer') as string,
    currentUser: '' as string,
    currentUserRoles: [] as string[],
    /**
     * 打字机定时器。
     * key=trace_id，value=window.setInterval 返回值。
     * 该字段只在前端运行时使用，不写入 localStorage。
     */
    typingTimersByTrace: {} as Record<string, number>
  }),

  getters: {
    /** 左侧搜索过滤后的会话列表。 */
    filteredSessions(state): ChatSession[] {
      const keyword = state.searchKeyword.trim().toLowerCase()
      if (!keyword) return state.sessions
      return state.sessions.filter(session => {
        return [session.title, session.last_message, session.last_trace_id]
          .filter(Boolean)
          .some(value => String(value).toLowerCase().includes(keyword))
      })
    },
    /** 当前会话对象。 */
    currentSession(state): ChatSession | undefined {
      return state.sessions.find(session => sessionIdOf(session) === state.currentSessionId)
    },
    /** 当前会话的聊天消息。 */
    currentMessages(state): ChatMessage[] {
      return state.messagesBySession[state.currentSessionId] || []
    },
    /** 当前会话正在展示的 trace_id。 */
    activeTraceId(state): string {
      return state.activeTraceIdBySession[state.currentSessionId] || ''
    },
    /** 当前 trace 的原始事件列表。 */
    currentEvents(state): StreamEvent[] {
      const traceId = state.activeTraceIdBySession[state.currentSessionId]
      return traceId ? state.eventsByTrace[traceId] || [] : []
    },
    /** 当前 trace 的工具结果。 */
    currentToolResults(state): ToolResult[] {
      const traceId = state.activeTraceIdBySession[state.currentSessionId]
      return traceId ? state.toolResultsByTrace[traceId] || [] : []
    },
    /** 当前 trace 的整批安全裁决。 */
    currentPolicyVerdict(state): PolicyVerdict | null {
      const traceId = state.activeTraceIdBySession[state.currentSessionId]
      return traceId ? state.policyVerdictByTrace[traceId] || null : null
    },
    /** 当前 trace 的内联审批数据。 */
    currentApproval(state): InlineApproval | null {
      const traceId = state.activeTraceIdBySession[state.currentSessionId]
      return traceId ? state.approvalByTrace[traceId] || null : null
    },
    /** 当前 trace 的审计哈希链节点。 */
    currentAuditNodes(state): AuditAppendedData[] {
      const traceId = state.activeTraceIdBySession[state.currentSessionId]
      return traceId ? state.auditNodesByTrace[traceId] || [] : []
    },
    /** 当前 trace 的 RCA 报告。 */
    currentRcaReport(state): RcaReport | null {
      const traceId = state.activeTraceIdBySession[state.currentSessionId]
      return traceId ? state.rcaReportByTrace[traceId] || null : null
    },
    /** 当前 trace 的 RCA LLM 自然语言摘要（可选，无则 null）。 */
    currentRcaLlmSummary(state): string | null {
      const traceId = state.activeTraceIdBySession[state.currentSessionId]
      return traceId ? state.rcaLlmSummaryByTrace[traceId] || null : null
    }
  },

  actions: {
    /**
     * 将当前 chat store 的可恢复数据写入 localStorage。
     *
     * 不保存：
     * - stream EventSource 连接；
     * - typingTimersByTrace 定时器；
     * 这两类对象刷新后必须重新建立，不能序列化。
     */
    persist() {
      saveChatState({
        sessions: this.sessions,
        currentSessionId: this.currentSessionId,
        messagesBySession: this.messagesBySession,
        traceIdsBySession: this.traceIdsBySession,
        activeTraceIdBySession: this.activeTraceIdBySession,
        eventsByTrace: this.eventsByTrace,
        toolResultsByTrace: this.toolResultsByTrace,
        policyVerdictByTrace: this.policyVerdictByTrace,
        approvalByTrace: this.approvalByTrace,
        auditNodesByTrace: this.auditNodesByTrace,
        rcaReportByTrace: this.rcaReportByTrace,
        rcaLlmSummaryByTrace: this.rcaLlmSummaryByTrace
      })
    },

    /** 如果首次进入页面没有任何会话，则创建默认会话。 */
    ensureDefaultSession() {
      if (this.sessions.length) return
      const defaultSession = normalizeSession({ session_id: 'local', title: '默认会话' })
      this.sessions = [defaultSession]
      this.currentSessionId = defaultSession.session_id
      this.messagesBySession[defaultSession.session_id] = []
      this.traceIdsBySession[defaultSession.session_id] = []
    },

    /**
     * 初始化会话数据。
     *
     * 读取顺序：
     * 1. 先读 localStorage，恢复用户上次会话、消息、trace；
     * 2. 再调 getSessions()，由 api/chat.ts 决定真实后端或 Mock；
     * 3. 后端未接入时保留本地默认会话。
     */
    async initSessions() {
      const cached = loadChatState()
      if (cached?.sessions?.length) {
        this.sessions = cached.sessions.map(normalizeSession)
        this.currentSessionId = cached.currentSessionId || sessionIdOf(this.sessions[0])
        this.messagesBySession = cached.messagesBySession || {}
        this.traceIdsBySession = cached.traceIdsBySession || {}
        this.activeTraceIdBySession = cached.activeTraceIdBySession || {}
        this.eventsByTrace = cached.eventsByTrace || {}
        this.toolResultsByTrace = cached.toolResultsByTrace || {}
        this.policyVerdictByTrace = cached.policyVerdictByTrace || {}
        this.approvalByTrace = cached.approvalByTrace || {}
        this.auditNodesByTrace = cached.auditNodesByTrace || {}
        this.rcaReportByTrace = cached.rcaReportByTrace || {}
        this.rcaLlmSummaryByTrace = cached.rcaLlmSummaryByTrace || {}
      }

      this.ensureDefaultSession()

      try {
        const remoteSessions = await getSessions()
        if (remoteSessions?.length) {
          const normalized = remoteSessions.map(normalizeSession)
          const localIds = new Set(this.sessions.map(sessionIdOf))
          this.sessions = [...this.sessions, ...normalized.filter(item => !localIds.has(sessionIdOf(item)))]
          this.persist()
        }
      } catch {
        // 后端会话接口未就绪且未开启 Mock 时，继续使用 localStorage / 默认会话。
      }
    },

    /** 更新左侧会话搜索关键字。 */
    setSearchKeyword(keyword: string) {
      this.searchKeyword = keyword
    },

    /**
     * 创建新会话。
     *
     * 名字保留 createLocalSession 是为了兼容旧调用，但内部已经先走 api/createSession()。
     */
    async createLocalSession(title = '新会话') {
      let session = normalizeSession({ title })
      try {
        session = normalizeSession(await createSession(title))
      } catch {
        // 未开启 Mock 且真实后端不可用时，仍允许创建本地会话，避免页面卡死。
      }
      this.sessions.unshift(session)
      this.currentSessionId = session.session_id
      this.messagesBySession[session.session_id] = []
      this.traceIdsBySession[session.session_id] = []
      this.persist()
      return session
    },

    /** 切换会话。
     *
     * 最小方案：如果当前 trace 处于 pending approval，不关闭 SSE，
     * 否则 resume 后续事件可能丢失。
     * 长期优化建议：维护 streamsByTrace，每个 trace 单独管理 EventSource。
     */
    switchSession(sessionId: string) {
      if (!sessionId || sessionId === this.currentSessionId) return
      const _currentTraceId = this.activeTraceId
      const _currentApproval = _currentTraceId ? this.approvalByTrace[_currentTraceId] : null
      if (!_currentApproval || _currentApproval.status !== 'pending') {
        this.stream?.close()
        this.stream = null
      }
      this.currentSessionId = sessionId
      this.messagesBySession[sessionId] ||= []
      this.traceIdsBySession[sessionId] ||= []


      this.persist()
    },

    /** 删除会话，并清理该会话下所有 trace 级缓存。 */
    async deleteSession(sessionId: string) {
      if (this.sessions.length <= 1) return
      try {
        await deleteSessionApi(sessionId)
      } catch {
        // 后端不可用时只删除本地数据。
      }
      const traceIds = this.traceIdsBySession[sessionId] || []
      this.sessions = this.sessions.filter(session => sessionIdOf(session) !== sessionId)
      delete this.messagesBySession[sessionId]
      delete this.traceIdsBySession[sessionId]
      delete this.activeTraceIdBySession[sessionId]
      for (const traceId of traceIds) {
        this.stopAssistantTyping(traceId)
        delete this.eventsByTrace[traceId]
        delete this.toolResultsByTrace[traceId]
        delete this.policyVerdictByTrace[traceId]
        delete this.approvalByTrace[traceId]
        delete this.auditNodesByTrace[traceId]
        delete this.rcaReportByTrace[traceId]
        delete this.rcaLlmSummaryByTrace[traceId]
      }
      if (this.currentSessionId === sessionId) {
        this.currentSessionId = sessionIdOf(this.sessions[0])
      }
      this.persist()
    },

    /** 重命名会话。 */
    async renameSession(sessionId: string, title: string) {
      const cleanTitle = title.trim()
      if (!cleanTitle) return
      try {
        await renameSessionApi(sessionId, cleanTitle)
      } catch {
        // 后端不可用时只改本地名称。
      }
      const session = this.sessions.find(item => sessionIdOf(item) === sessionId)
      if (session) {
        session.title = cleanTitle
        session.updated_at = nowIso()
      }
      this.persist()
    },

    /** 搜索会话。真实模式下只做前端本地过滤，不调用后端 search 接口（后端未实现）。 */
    async searchSessions(keyword: string) {
      this.searchKeyword = keyword
      if (!keyword.trim()) return
      // Mock 模式：可以调后端 search 补充远程结果
      // 真实模式：后端未实现 /api/chat/sessions/search，只做本地过滤（getter filteredSessions）
    },

    /** 向指定会话追加一条聊天消息。 */
    addMessage(sessionId: string, message: ChatMessage) {
      this.messagesBySession[sessionId] ||= []
      this.messagesBySession[sessionId].push(message)
      const session = this.sessions.find(item => sessionIdOf(item) === sessionId)
      if (session) {
        session.last_message = message.approval ? '本批计划需要审批' : message.content
        session.updated_at = message.created_at
      }
      this.persist()
    },

    /** 根据 trace_id 找到其所属 session_id。 */
    sessionIdForTrace(traceId: string) {
      for (const [sessionId, traceIds] of Object.entries(this.traceIdsBySession)) {
        if (traceIds.includes(traceId)) return sessionId
      }
      return this.currentSessionId
    },

    /** 为一次新的 trace 初始化数据容器。 */
    prepareTrace(traceId: string, sessionId?: string) {
      const targetSessionId = sessionId || this.currentSessionId
      this.activeTraceIdBySession[targetSessionId] = traceId
      this.traceIdsBySession[targetSessionId] ||= []
      if (!this.traceIdsBySession[targetSessionId].includes(traceId)) {
        this.traceIdsBySession[targetSessionId].push(traceId)
      }
      this.eventsByTrace[traceId] = []
      this.toolResultsByTrace[traceId] = []
      this.policyVerdictByTrace[traceId] = null
      this.approvalByTrace[traceId] = null
      this.auditNodesByTrace[traceId] = []
      this.rcaReportByTrace[traceId] = null
      this.rcaLlmSummaryByTrace[traceId] = null
      const session = this.sessions.find(item => sessionIdOf(item) === targetSessionId)
      if (session) session.last_trace_id = traceId
      this.persist()
    },

    /**
     * 在中间聊天区插入审批卡片消息。
     *
     * 为什么审批放中间：
     * - 用户是在对话中触发风险计划的；
     * - 审批也是当前对话流程的一部分；
     * - 右侧只展示执行证据和链路，不承载审批操作按钮。
     */
    addInlineApprovalMessage(sessionId: string, approval: InlineApproval) {
      const exists = (this.messagesBySession[sessionId] || []).some(item => item.approval?.trace_id === approval.trace_id)
      if (exists) return
      this.addMessage(sessionId, {
        id: uid('msg_approval'),
        role: 'system',
        content: '本批计划需要审批。请在此消息中处理，批准/拒绝作用于整批工具。',
        created_at: nowIso(),
        trace_id: approval.trace_id,
        approval
      })
    },

    /** 同步更新对话区审批卡片状态。 */
    updateApprovalStatusInMessages(traceId: string, status: InlineApproval['status']) {
      for (const messages of Object.values(this.messagesBySession)) {
        const message = messages.find(item => item.approval?.trace_id === traceId)
        if (message?.approval) message.approval.status = status
      }
    },

    /**
     * 停止某个 trace 的打字机效果。
     * 切换/删除/错误时调用，避免旧定时器继续写消息。
     */
    stopAssistantTyping(traceId: string) {
      const timer = this.typingTimersByTrace[traceId]
      if (timer) {
        window.clearTimeout(timer)
        delete this.typingTimersByTrace[traceId]
      }
    },

    /**
     * 创建/复用 assistant 消息，按打字机节奏逐步追加文本。
     *
     * 复用场景：verified 先到（summary=”ok”，打字机极快），natural_language
     * 紧接着到（携带真实 LLM 文本）。本方法检测同 trace 已有 assistant 消息时
     * 就地重置，避免出现两条 assistant 消息。
     */
    startAssistantTyping(traceId: string, fullText: string) {
      const sessionId = this.sessionIdForTrace(traceId)
      this.stopAssistantTyping(traceId)
      this.messagesBySession[sessionId] ||= []

      // 同 trace 已有 assistant 消息则复用（natural_language 替换 verified 的 “ok”）
      const existing = [...this.messagesBySession[sessionId]].reverse().find(
        (m: ChatMessage) => m.role === 'assistant' && m.trace_id === traceId && (m.status === 'streaming' || m.status === 'done')
      )
      let messageId: string
      if (existing) {
        existing.content = ''
        existing.status = 'streaming'
        messageId = existing.id
      } else {
        messageId = uid('msg_typing')
        this.messagesBySession[sessionId].push({
          id: messageId,
          role: 'assistant',
          content: '',
          status: 'streaming',
          created_at: nowIso(),
          trace_id: traceId
        })
      }

      let index = 0
      const tick = () => {
        const message = this.messagesBySession[sessionId]?.find(item => item.id === messageId)
        if (!message) {
          this.stopAssistantTyping(traceId)
          return
        }

        const { step, delay } = typingStep(fullText, index)
        index = Math.min(fullText.length, index + step)
        message.content = fullText.slice(0, index)

        if (index >= fullText.length) {
          message.status = 'done'
          this.stopAssistantTyping(traceId)
          const session = this.sessions.find(item => sessionIdOf(item) === sessionId)
          if (session) {
            session.last_message = fullText
            session.updated_at = nowIso()
          }
          this.persist()
          return
        }

        this.typingTimersByTrace[traceId] = window.setTimeout(tick, delay)
      }

      this.typingTimersByTrace[traceId] = window.setTimeout(tick, 120)
    },

    /**
     * 消费后端/Mock 推来的单个 StreamEvent。
     *
     * 这里是前端数据管理核心：
     * - 所有事件先进入 eventsByTrace；
     * - 再按 type 拆分到工具结果、裁决、审批、RCA、审计链等结构；
     * - 页面组件只读 getter，不直接解析原始事件。
     */
    addEvent(event: StreamEvent) {
      const traceId = event.trace_id
      const sessionId = this.sessionIdForTrace(traceId)
      this.eventsByTrace[traceId] ||= []
      this.eventsByTrace[traceId].push(event)
      this.activeTraceIdBySession[sessionId] = traceId

      if (event.type === 'observation') {
        const results = (event.data.results || []) as ToolResult[]
        this.toolResultsByTrace[traceId] ||= []
        this.toolResultsByTrace[traceId].push(...results)
      }

      if (event.type === 'policy_verdict') {
        const verdict = (event.data.verdict as PolicyVerdict) || null
        this.policyVerdictByTrace[traceId] = verdict
        const session = this.sessions.find(item => sessionIdOf(item) === sessionId)
        if (session && verdict?.final_risk) session.risk_level = verdict.final_risk
      }

      if (event.type === 'await_approval') {
        const tools = (event.data.tools || []) as InlineApproval['tools']
        const approval: InlineApproval = {
          trace_id: traceId,
          reason: String(event.data.reason || '该批工具计划需要人工确认'),
          tools,
          approval_role: requiredRoleOf(tools),
          status: 'pending'
        }
        this.approvalByTrace[traceId] = approval
        this.addInlineApprovalMessage(sessionId, approval)
        const session = this.sessions.find(item => sessionIdOf(item) === sessionId)
        if (session) session.pending_approval_count = Math.max(1, session.pending_approval_count || 0)
      }

      if (event.type === 'tool_result') {
        const result = event.data.result as ToolResult | undefined
        if (result) {
          this.toolResultsByTrace[traceId] ||= []
          this.toolResultsByTrace[traceId].push(result)
        }
      }

      if (event.type === 'audit_appended') {
        this.auditNodesByTrace[traceId] ||= []
        this.auditNodesByTrace[traceId].push(event.data as unknown as AuditAppendedData)
      }

      if (event.type === 'rca') {
        this.rcaReportByTrace[traceId] = (event.data.report as RcaReport) || null
        // RCA P4：后端 rca 事件可选带 llm_summary（LLM 自然语言根因摘要）。
        // 拒答/注入拦截/NullRCA 时该字段不存在 → 存 null，展示层零感知兼容。
        this.rcaLlmSummaryByTrace[traceId] = (event.data.llm_summary as string) || null
      }

      // 守卫语义与下方 verified 一致：只在明确 REJECTED 时拦截打字机。
      // 后端正常 FINISHED 路径 emit 的 natural_language 不带 state 字段（orchestrator.py:579），
      // 若用 state === 'FINISHED' 正向校验会把无 state 的正常总结全部误拦，导致 LLM 回复不显示。
      if (event.type === 'natural_language' && (event.data as any)?.state !== 'REJECTED') {
        const nlData = event.data as { text: string; sensitive_filtered: boolean }
        const fullText = nlData.sensitive_filtered
          ? nlData.text + '\n(已过滤敏感字段)'
          : nlData.text
        this.startAssistantTyping(traceId, fullText)
      }

      if (event.type === 'verified' && (event.data as any)?.state !== 'REJECTED') {
        this.loading = false
        this.startAssistantTyping(traceId, String(event.data.summary || '任务执行完成。'))
      }

      if (event.type === 'error') {
        this.loading = false
        this.stopAssistantTyping(traceId)
        this.addMessage(sessionId, {
          id: uid('msg_error'),
          role: 'assistant',
          status: 'error',
          content: `执行失败：${event.data.message || '未知错误'}（阶段：${event.data.phase || '-'}）`,
          created_at: nowIso(),
          trace_id: traceId
        })
      }

      if (event.type === 'rejected') {
        this.loading = false
        this.stopAssistantTyping(traceId)
        const data = event.data as { reason: string; cause: string; denied_tools: string[] }
        const toolsSuffix = data.denied_tools?.length ? `，被拒工具：${data.denied_tools.join(', ')}` : ''
        if (data.cause === 'policy_deny') {
          this.addMessage(sessionId, {
            id: uid('msg_denied'),
            role: 'system',
            status: 'done',
            content: `⛔ 操作被安全策略拒绝：${data.reason || '不允许执行'}${toolsSuffix}`,
            created_at: nowIso(),
            trace_id: traceId
          })
        } else if (data.cause === 'injection') {
          this.addMessage(sessionId, {
            id: uid('msg_inject'),
            role: 'system',
            status: 'done',
            content: `⛔ 输入被安全策略拦截：${data.reason || '不允许执行'}${toolsSuffix}`,
            created_at: nowIso(),
            trace_id: traceId
          })
        } else {
          this.addMessage(sessionId, {
            id: uid('msg_rejected'),
            role: 'system',
            status: 'done',
            content: `⛔ 审批被拒绝：${data.reason || '未说明原因'}${toolsSuffix}`,
            created_at: nowIso(),
            trace_id: traceId
          })
        }
      }

      this._debouncedPersist()
    },

    /**
     * 发送用户消息。
     *
     * 数据流：
     * 1. ChatView 点击“发送”；
     * 2. store 记录用户消息；
     * 3. 调 src/api/chat.ts 的 sendMessage({ session_id, message })；
     * 4. api 层在 Mock 模式返回模拟 trace_id，在真实模式请求后端；
     * 5. store 根据 trace_id 建立 connectChatStream；
     * 6. 后端或 api mock 持续推送 StreamEvent；
     * 7. addEvent() 统一入库并驱动页面刷新。
     */
        /** Throttled persist — limits localStorage writes to once per 1.5s during SSE streaming. */
    _debouncedPersist() {
      if (_persistTimer) clearTimeout(_persistTimer)
      _persistTimer = setTimeout(() => { this.persist(); _persistTimer = null }, 1500)
    },

    async fetchWhoami() {
      if (isMockEnabled()) return
      try {
        const res = await request.get('/api/auth/whoami') as unknown as { user: string; roles: string[]; mode: string }
        this.currentUser = res.user ?? 'dev'
        const roles = Array.isArray(res.roles) ? res.roles : []
        this.currentUserRoles = roles
        const rank: Record<string, number> = { viewer: 1, auditor: 1, operator: 2, admin: 3 }
        this.currentUserRole = roles.reduce(
          (top: string, r: string) => (rank[r] ?? 0) > (rank[top] ?? 0) ? r : top,
          'viewer'
        )
      } catch { /* silent: whoami unavailable, remain viewer */ }
    },

async sendMessage(content: string) {
      const cleanContent = content.trim()
      if (!cleanContent) return
      this.ensureDefaultSession()
      this.loading = true
      this.addMessage(this.currentSessionId, {
        id: uid('msg_user'),
        role: 'user',
        content: cleanContent,
        created_at: nowIso(),
        status: 'done'
      })

      try {
        const response = await sendMessageApi({
          session_id: this.currentSessionId,
          message: cleanContent
        })

        const traceId = response.trace_id
        this.prepareTrace(traceId)
        this.stream?.close()
        const capturedSessionId = this.currentSessionId
        this.stream = connectChatStream(
          traceId,
          response.stream_url,
          event => this.addEvent(event),
          error => {
            this.loading = false
            this.addMessage(capturedSessionId, {
              id: uid('msg_error'),
              role: 'assistant',
              status: 'error',
              content: `事件流连接失败：${error.type || 'unknown'}`,
              created_at: nowIso(),
              trace_id: traceId
            })
          },
          () => {
            // onDone: SSE transport 结束，只负责清理状态，不写入业务事件
            this.loading = false
          }
        )
      } catch (error) {
        this.loading = false
        this.addMessage(this.currentSessionId, {
          id: uid('msg_error'),
          role: 'assistant',
          status: 'error',
          content: `请求失败：${(error as Error).message}。如需本地演示，请确认 .env.development 中 VITE_MOCK_ENABLED=true。`,
          created_at: nowIso()
        })
      }
    },

    /** 对话内批准当前批次原子计划。使用传入 traceId，禁止默认使用 activeTraceId。 */
    async approveInlinePlan(traceId: string, _comment = '确认执行本批计划') {
      const approval = traceId ? this.approvalByTrace[traceId] : null
      if (!traceId || !approval) return
      try {
        await resumeApproval({ trace_id: traceId, approved: true })
        approval.status = 'approved'
        this.updateApprovalStatusInMessages(traceId, 'approved')
        const session = this.sessions.find(item => sessionIdOf(item) === this.sessionIdForTrace(traceId))
        if (session) session.pending_approval_count = 0
        this.persist()
      } catch (error) {
        this.addMessage(this.sessionIdForTrace(traceId), {
          id: uid('msg_error'),
          role: 'system',
          status: 'error',
          content: `审批提交失败：${(error as Error).message}。请稍后重试。`,
          created_at: nowIso(),
          trace_id: traceId
        })
      }
    },

    /** 对话内拒绝当前批次原子计划。使用传入 traceId。 */
    async rejectInlinePlan(traceId: string, _comment = '拒绝执行本批计划') {
      const approval = traceId ? this.approvalByTrace[traceId] : null
      if (!traceId || !approval) return
      try {
        await resumeApproval({ trace_id: traceId, approved: false })
        approval.status = 'rejected'
        this.updateApprovalStatusInMessages(traceId, 'rejected')
        const session = this.sessions.find(item => sessionIdOf(item) === this.sessionIdForTrace(traceId))
        if (session) session.pending_approval_count = 0
        this.persist()
      } catch (error) {
        this.addMessage(this.sessionIdForTrace(traceId), {
          id: uid('msg_error'),
          role: 'system',
          status: 'error',
          content: `拒绝提交失败：${(error as Error).message}。请稍后重试。`,
          created_at: nowIso(),
          trace_id: traceId
        })
      }
    },

    /** 权限不足时，在对话中申请转管理员审批。使用传入 traceId。 */
    async escalateInlinePlan(traceId: string, reason = '当前用户权限不足，申请管理员审批') {
      const approval = traceId ? this.approvalByTrace[traceId] : null
      if (!traceId || !approval) return
      const response = await escalateApproval({ trace_id: traceId, comment: reason, tools: approval.tools })
      approval.status = 'escalated'
      this.updateApprovalStatusInMessages(traceId, 'escalated')
      this.addMessage(this.sessionIdForTrace(traceId), {
        id: uid('msg_escalated'),
        role: 'system',
        status: 'done',
        content: response.message || '已提交管理员审批，请等待管理员在审批页处理。',
        created_at: nowIso(),
        trace_id: traceId
      })
      this.persist()
    }
  }
})
