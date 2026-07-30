import type { ChatSession, SendMessageRequest, SendMessageResponse, StreamEvent } from '@/types/chat'

/** Backend contract: contracts/untrusted.py UNTRUSTED_WRAP_TOKEN. */
const UNTRUSTED_WRAP_TOKEN = '<<UNTRUSTED_TOOL_OUTPUT>>'
import type {
  ApprovalItem,
  ApprovalListResponse,
  EscalateApprovalRequest,
  EscalateApprovalResponse,
  ResumeApprovalRequest,
  ResumeApprovalResponse
} from '@/types/approval'
import type { RcaProblemType, RcaResult } from '@/types/rca'

/**
 * mock.ts
 *
 * 前端 API Mock 数据模块。
 *
 * 这个文件的定位：
 * - 页面不直接写假数据；
 * - Store 不直接拼假 StreamEvent；
 * - 所有 Mock 都放在 api 层，由 api/chat.ts、api/approval.ts、api/rca.ts 调用。
 *
 * 这样做的好处：
 * 1. 页面点击发送后，仍然走 ChatView -> Store -> API 的真实数据路径；
 * 2. VITE_MOCK_ENABLED=true 时，由本文件模拟后端返回；
 * 3. VITE_MOCK_ENABLED=false 时，API 文件会切换到真实后端；
 * 4. 以后联调后端时，页面和 Store 不需要重写。
 *
 * 当前 Mock 覆盖范围：
 * - 会话管理：列表、新建、删除、重命名、搜索；
 * - 智能对话：POST /api/chat + mock:// 事件流；
 * - 事件流：stream.py 规定的 11 种 EventType；
 * - 审批：resume 与 escalate；
 * - RCA：四类演示场景报告。
 */

const MOCK_SESSION_KEY = 'KS_SAFEOPS_MOCK_SESSIONS_V1'

/** 生成前端 Mock ID。 */
function uid(prefix = 'id') {
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

/** 当前时间 ISO 字符串，用于会话、审批单创建时间。 */
function nowIso() {
  return new Date().toISOString()
}

/** 当前 epoch 秒，符合 stream.py 中 StreamEvent.ts 字段约定。 */
function nowEpochSeconds() {
  return Date.now() / 1000
}

/** 从 localStorage 读取 Mock 会话列表。 */
function readMockSessions(): ChatSession[] {
  try {
    const raw = localStorage.getItem(MOCK_SESSION_KEY)
    return raw ? JSON.parse(raw) as ChatSession[] : []
  } catch {
    return []
  }
}

/** 将 Mock 会话列表写入 localStorage。 */
function writeMockSessions(sessions: ChatSession[]) {
  try {
    localStorage.setItem(MOCK_SESSION_KEY, JSON.stringify(sessions))
  } catch {
    // localStorage 写入失败不影响主流程，最多导致刷新后 mock 会话不保留。
  }
}

/**
 * Mock：GET /api/chat/sessions
 *
 * 返回左侧会话列表。字段与 ChatSession 对齐。
 */
export async function mockGetSessions(): Promise<ChatSession[]> {
  return readMockSessions()
}

/**
 * Mock：POST /api/chat/sessions
 *
 * 请求参数：title，可选。
 * 返回新建会话对象。
 */
export async function mockCreateSession(title = '新会话'): Promise<ChatSession> {
  const session: ChatSession = {
    session_id: uid('session'),
    id: uid('session_legacy'),
    title,
    created_at: nowIso(),
    updated_at: nowIso(),
    last_message: '',
    pending_approval_count: 0
  }
  writeMockSessions([session, ...readMockSessions()])
  return session
}

/** Mock：DELETE /api/chat/sessions/{session_id}。 */
export async function mockDeleteSession(sessionId: string) {
  writeMockSessions(readMockSessions().filter(item => item.session_id !== sessionId && item.id !== sessionId))
  return { ok: true }
}

/** Mock：PATCH /api/chat/sessions/{session_id}。 */
export async function mockRenameSession(sessionId: string, title: string): Promise<ChatSession> {
  const sessions = readMockSessions()
  const target = sessions.find(item => item.session_id === sessionId || item.id === sessionId)
  if (target) {
    target.title = title
    target.updated_at = nowIso()
    writeMockSessions(sessions)
    return target
  }
  return { session_id: sessionId, id: sessionId, title, updated_at: nowIso() }
}

/** Mock：GET /api/chat/sessions/search?keyword=xxx。 */
export async function mockSearchSessions(keyword: string): Promise<ChatSession[]> {
  const lower = keyword.trim().toLowerCase()
  if (!lower) return readMockSessions()
  return readMockSessions().filter(item => {
    return [item.title, item.last_message, item.last_trace_id]
      .filter(Boolean)
      .some(value => String(value).toLowerCase().includes(lower))
  })
}

/** Mock：GET /api/chat/sessions/{session_id}，后续可扩展为返回历史消息。 */
export async function mockGetSessionDetail(sessionId: string) {
  return { session_id: sessionId, messages: [] }
}

interface MockTraceRecord {
  traceId: string
  sessionId: string
  userMessage: string
  initialEvents: StreamEvent[]
  approvedEvents: StreamEvent[]
  rejectedEvents: StreamEvent[]
  controller?: MockStreamController
}

interface MockStreamController {
  close: () => void
  emitAfterApproval: (approved: boolean) => Promise<void>
}

/** 每一次 mockSendMessage 生成一条 trace，并暂存在这里，等待 connectMockChatStream 消费。 */
const mockTraces = new Map<string, MockTraceRecord>()

/**
 * Mock：POST /api/chat
 *
 * 请求参数：
 * - session_id：当前会话 ID；
 * - message：用户自然语言问题。
 *
 * 返回数据：
 * - trace_id：本次请求链路 ID；
 * - session_id：原样返回；
 * - stream_url：mock://chat/{trace_id}，后续 connectChatStream 会识别为 Mock 事件流。
 */
export async function mockSendMessage(data: SendMessageRequest): Promise<SendMessageResponse> {
  const traceId = uid('trace')
  const sessionId = data.session_id || 'local'
  const userMessage = data.message || '帮我看看磁盘为什么快满了'

  mockTraces.set(traceId, {
    traceId,
    sessionId,
    userMessage,
    initialEvents: buildInitialEvents(traceId, userMessage),
    approvedEvents: buildApprovedEvents(traceId),
    rejectedEvents: buildRejectedEvents(traceId, 'user_reject')
  })

  return {
    trace_id: traceId,
    session_id: sessionId,
    stream_url: `mock://chat/${traceId}`
  }
}

/** Mock 事件流连接类型。只需要提供 close()，让 Store 可以统一关闭连接。 */
export type MockChatStreamConnection = Pick<EventSource, 'close'>

/**
 * Mock：SSE 事件流。
 *
 * 真实后端会持续推送 StreamEvent；这里用 setTimeout 按顺序模拟。
 * 初始事件会推到 await_approval，然后停住等待用户审批。
 * 用户点击批准/拒绝后，mockResumeApproval 会调用 emitAfterApproval 继续推后半段事件。
 */
export function connectMockChatStream(
  traceId: string,
  onMessage: (event: StreamEvent) => void,
  onError?: (error: Event) => void,
  onDone?: () => void
): MockChatStreamConnection {
  const record = mockTraces.get(traceId)
  let closed = false
  const timers: ReturnType<typeof setTimeout>[] = []

  if (!record) {
    const timer = setTimeout(() => onError?.(new Event('mock-trace-not-found')), 0)
    timers.push(timer)
    return {
      close() {
        closed = true
        timers.forEach(clearTimeout)
      }
    }
  }

  const emitSequence = async (events: StreamEvent[], intervalMs: number) => {
    for (let index = 0; index < events.length; index += 1) {
      if (closed) return
      await new Promise<void>(resolve => {
        const timer = setTimeout(resolve, intervalMs)
        timers.push(timer)
      })
      if (closed) return
      onMessage({ ...events[index], ts: nowEpochSeconds() })
    }
  }

  const controller: MockStreamController = {
    close() {
      closed = true
      timers.forEach(clearTimeout)
    },
    async emitAfterApproval(approved: boolean) {
      await emitSequence(approved ? record.approvedEvents : record.rejectedEvents, 360)
      onDone?.()
    }
  }

  // 如果没有 await_approval（无审批场景），初始事件发出后直接 onDone
  const hasApproval = record.initialEvents.some(e => e.type === 'await_approval')
  if (!hasApproval) {
    void emitSequence(record.initialEvents, 420).then(() => onDone?.())
    return controller
  }

  record.controller = controller
  void emitSequence(record.initialEvents, 420)

  return controller
}

/**
 * Mock：POST /api/approvals/resume
 *
 * approved=true 时推送 executing/tool_result/verified/rca/audit_appended；
 * approved=false 时推送 verified/audit_appended，表示整批拒绝。
 */
export async function mockResumeApproval(data: ResumeApprovalRequest): Promise<ResumeApprovalResponse> {
  const record = mockTraces.get(data.trace_id)
  await record?.controller?.emitAfterApproval(data.approved)
  return {
    trace_id: data.trace_id,
    accepted: data.approved
  }
}

/**
 * Mock：POST /api/approvals/escalate
 *
 * 该接口只提交管理员审批申请，不继续执行工具。
 */
export async function mockEscalateApproval(data: EscalateApprovalRequest): Promise<EscalateApprovalResponse> {
  return {
    trace_id: data.trace_id,
    status: 'submitted',
    message: `已提交管理员审批，等待具备权限的人员处理 ${data.tools.length} 个工具。`
  }
}

/**
 * Mock：GET /api/approvals?status=pending。
 *
 * 之七十五 M-8：返回**与后端同构的信封** { items, total }，不再返回裸数组。
 * 之七十四的审批页白屏正是信封错配——后端返回 { items, total } 而前端按裸数组
 * 消费。mock 若返回裸数组，则 approval.ts 里的 `.items` 解包在 mock 模式下
 * 永远不被执行，这类错配无法在 mock 联调中暴露，只能等真接后端才炸。
 * mock 与真后端信封同构是让 mock 具备"提前发现错配"能力的前提。
 */
export async function mockGetPendingApprovals(): Promise<ApprovalListResponse> {
  const items: ApprovalItem[] = [
    {
      trace_id: 'mock_trace_disk_full',
      user_intent: '压缩并轮转 /var/log/app.log',
      risk_level: 'R2',
      approval_role: 'operator',
      state: 'WAIT_APPROVAL',
      created_at: nowIso()
    }
  ]
  return { items, total: items.length }
}

/** Mock：GET /api/approvals/{trace_id}。 */
export async function mockGetApprovalDetail(traceId: string): Promise<ApprovalItem> {
  const { items } = await mockGetPendingApprovals()
  return items.find(item => item.trace_id === traceId) || items[0]
}

/** Mock：POST /api/approvals/{trace_id}/approve。 */
export async function mockApproveAction(traceId: string) {
  return { trace_id: traceId, decision: 'approved', accepted: true }
}

/** Mock：POST /api/approvals/{trace_id}/reject。 */
export async function mockRejectAction(traceId: string, comment?: string) {
  return { trace_id: traceId, decision: 'rejected', accepted: true, comment }
}

/** Mock RCA 任务缓存：startRcaAnalysis 生成 trace_id，getRcaResult 再按 trace_id 读取。 */
const mockRcaTasks = new Map<string, RcaResult>()

/** Mock：POST /api/rca/analyze。 */
export async function mockStartRcaAnalysis(data: { problem_type: RcaProblemType; description: string }): Promise<{ trace_id: string }> {
  const traceId = uid('rca_trace')
  mockRcaTasks.set(traceId, buildRcaResult(traceId, data.problem_type, data.description))
  return { trace_id: traceId }
}

/** Mock：GET /api/rca/{trace_id}。 */
export async function mockGetRcaResult(traceId: string): Promise<RcaResult> {
  return mockRcaTasks.get(traceId) || buildRcaResult(traceId, 'disk_full', '根分区使用率超过 90%，请分析原因并给出安全建议')
}

/** 构造一条 StreamEvent。 */
function event(traceId: string, type: StreamEvent['type'], data: StreamEvent['data']): StreamEvent {
  return { trace_id: traceId, type, ts: nowEpochSeconds(), data }
}

/** 构造初始事件流：意图、观测、计划、裁决、等待审批、审计。 */
function buildInitialEvents(traceId: string, userMessage: string): StreamEvent[] {
  const isNginx = /nginx|服务|重启/.test(userMessage)
  const intentName = isNginx ? 'service_restart_check' : 'disk_full_diagnosis'

  return [
    event(traceId, 'intent_parsed', {
      intent: {
        intent: intentName,
        confidence: 0.93,
        need_observation: true,
        candidate_tools: [
          { tool: 'disk.usage', args: { path: '/' }, risk_hint: 'R0', justification: '先读取根分区使用率' },
          { tool: 'disk.large_files', args: { path: '/var/log', min_size_mb: 500 }, risk_hint: 'R1', justification: '定位大文件来源' },
          { tool: 'file.lsof_check', args: { path: '/var/log/app.log' }, risk_hint: 'R1', justification: '确认日志文件是否仍被进程占用' }
        ],
        risk_hint: 'medium',
        justification: `用户输入：${userMessage}。系统需要先采集证据，再给出安全处理建议。`
      }
    }),
    event(traceId, 'observation', {
      results: [
        {
          tool: 'disk.usage',
          args: { path: '/' },
          exit_code: 0,
          stdout_truncated: 'Filesystem / 使用率 92%，/var/log 所在分区增长明显',
          is_untrusted: true,
          wrap_token: UNTRUSTED_WRAP_TOKEN
        },
        {
          tool: 'disk.large_files',
          args: { path: '/var/log', min_size_mb: 500 },
          exit_code: 0,
          stdout_truncated: '/var/log/app.log 18GB\n/var/lib/mysql/mysql-bin.000123 6GB',
          is_untrusted: true,
          wrap_token: UNTRUSTED_WRAP_TOKEN
        }
      ]
    }),
    event(traceId, 'plan_generated', {
      candidate_tools: [
        { tool: 'file.lsof_check', args: { path: '/var/log/app.log' }, risk_hint: 'R1', justification: '确认大日志是否被进程占用' },
        { tool: 'log.compress_rotate', args: { path: '/var/log/app.log' }, risk_hint: 'R2', justification: '压缩并轮转日志，避免直接删除' }
      ]
    }),
    event(traceId, 'policy_verdict', {
      verdict: {
        decision: 'confirm',
        final_risk: 'R2',
        matched_rules: ['LOG001', 'DBLOG001'],
        reason: '本批计划包含日志轮转操作，同时检测到数据库 binlog，必须避免直接删除并进行整批确认。',
        safer_alternative: '压缩归档普通日志；数据库 binlog 交由 DBA 或备份策略处理。',
        approval_required: true,
        approval_role: 'operator'
      },
      per_tool: [
        {
          tool: 'file.lsof_check',
          verdict: {
            decision: 'allow', final_risk: 'R1', matched_rules: [], reason: '只读检查文件占用，允许执行。', safer_alternative: null, approval_required: false, approval_role: null
          }
        },
        {
          tool: 'log.compress_rotate',
          verdict: {
            decision: 'confirm', final_risk: 'R2', matched_rules: ['LOG001'], reason: '日志轮转属于可逆变更，需要确认。', safer_alternative: '先压缩归档，不直接删除。', approval_required: true, approval_role: 'operator'
          }
        }
      ]
    }),
    event(traceId, 'await_approval', {
      reason: '多工具原子计划等待确认：批准后将按序执行 file.lsof_check 与 log.compress_rotate；拒绝则整批停止。',
      tools: [
        { tool: 'file.lsof_check', approval_role: null },
        { tool: 'log.compress_rotate', approval_role: 'operator' }
      ]
    }),
    event(traceId, 'audit_appended', { seq: 1, curr_hash: '4d5a88e09a8b0c1d99aa' })
  ]
}

/** 构造审批通过后的后续事件流。 */
function buildApprovedEvents(traceId: string): StreamEvent[] {
  return [
    event(traceId, 'executing', { tools: ['file.lsof_check', 'log.compress_rotate'] }),
    event(traceId, 'tool_result', {
      result: { tool: 'file.lsof_check', args: { path: '/var/log/app.log' }, exit_code: 0, stdout_truncated: '未发现数据库进程持有 /var/log/app.log，可进行轮转。', is_untrusted: true, wrap_token: UNTRUSTED_WRAP_TOKEN, duration_ms: 210 }
    }),
    event(traceId, 'tool_result', {
      result: { tool: 'log.compress_rotate', args: { path: '/var/log/app.log' }, exit_code: 0, stdout_truncated: '已生成 /var/log/app.log.20260610.gz，并创建新的 app.log。', is_untrusted: true, wrap_token: UNTRUSTED_WRAP_TOKEN, duration_ms: 1260 }
    }),
    event(traceId, 'verified', {
      summary: '整批工具计划已执行并验证：普通应用日志已压缩轮转；数据库 binlog 未执行删除，建议交由 DBA 策略处理。'
    }),
    event(traceId, 'rca', {
      report: buildRcaReportForChat(),
      llm_summary: '根分区磁盘占满，主要原因是 /var/log/app.log 应用日志长期未轮转积累了 18GB，建议立即压缩轮转该日志并配置 logrotate 策略，数据库 binlog 属于高风险数据不应直接删除。'
    }),
    event(traceId, 'audit_appended', { seq: 2, curr_hash: '9bf1193af72cd012884e' })
  ]
}

/** 构造审批拒绝后的事件流。 */
function buildRejectedEvents(traceId: string, cause: 'policy_deny' | 'user_reject'): StreamEvent[] {
  return [
    event(traceId, 'rejected', {
      reason: cause === 'policy_deny' ? '安全策略拦截：检测到高危操作' : 'operator rejected the plan',
      cause,
      denied_tools: cause === 'policy_deny' ? ['log.compress_rotate'] : [],
    }),
    event(traceId, 'audit_appended', { seq: 2, curr_hash: 'a77f09c118ee20dd231b' }),
  ]
}

/** ChatView rca 事件中使用的 RCA 报告。 */
function buildRcaReportForChat() {
  return {
    problem_type: 'disk_full',
    summary: '根分区占用过高，主要由应用日志持续增长导致；数据库 binlog 属高风险数据，不应直接删除。',
    root_cause_candidates: [
      { cause: '应用日志未轮转导致 /var/log/app.log 持续增长', confidence: 0.87, evidence_refs: ['ev_001', 'ev_002'], evidence: ['根分区使用率 92%', '/var/log/app.log 占用 18GB'] }
    ],
    evidence_chain: [
      { id: 'ev_001', source_tool: 'disk.usage', title: '根分区占用高', detail: '根分区使用率 92%', is_untrusted: true },
      { id: 'ev_002', source_tool: 'disk.large_files', title: '发现大日志文件', detail: '/var/log/app.log 18GB', is_untrusted: true }
    ],
    safe_actions: ['压缩并轮转 /var/log/app.log', '补充 logrotate 策略'],
    dangerous_actions_rejected: [
      { action: '直接删除数据库 binlog', reason: '可能破坏数据库恢复链路', rule_id: 'DBLOG001' }
    ],
    recommended_next_steps: ['观察轮转后磁盘占用', '确认日志增长来源', '为数据库 binlog 配置备份与过期策略']
  }
}

/** 独立 RCA 页面使用的四场景报告。 */
function buildRcaResult(traceId: string, problemType: RcaProblemType, description: string): RcaResult {
  const base = {
    trace_id: traceId,
    problem_type: problemType,
    recommended_next_steps: ['保留审计记录', '观察处理后的系统指标', '必要时提交管理员复核']
  }

  if (problemType === 'zombie_process') {
    return {
      ...base,
      summary: '检测到多个僵尸进程，根因更可能是父进程未正确回收子进程，而不是僵尸进程本身可被直接 kill。',
      root_cause_candidates: [
        { cause: '父进程未 wait 子进程导致 Z 状态堆积', confidence: 0.82, evidence: ['process.zombie_check 发现 5 个 Z 进程', 'PPID 均指向 app-worker'], evidence_refs: ['ev_z_001'] }
      ],
      evidence_chain: [
        { id: 'ev_z_001', source_tool: 'process.zombie_check', title: '发现僵尸进程', detail: 'STAT=Z count=5，父进程 app-worker', is_untrusted: true }
      ],
      evidence_tree: [{ id: 'zombie', label: '僵尸进程诊断', value: '5 个', children: [{ id: 'ppid', label: '父进程', value: 'app-worker' }] }],
      safe_actions: ['重启或修复父服务 app-worker', '检查父进程回收子进程逻辑'],
      dangerous_actions_rejected: [{ action: '直接 kill 僵尸进程', reason: '僵尸进程已退出，应处理父进程', rule_id: 'PROC001' }]
    }
  }

  if (problemType === 'io_high') {
    return {
      ...base,
      summary: 'I/O 异常主要来自日志快速写入，建议先定位写入进程并限制日志增长，而不是直接删除文件。',
      root_cause_candidates: [
        { cause: '应用日志高频写入导致 iowait 升高', confidence: 0.78, evidence: ['iowait 持续高于 30%', '/var/log/app.log 快速增长'], evidence_refs: ['ev_io_001'] }
      ],
      evidence_chain: [
        { id: 'ev_io_001', source_tool: 'disk.io_stat', title: 'iowait 偏高', detail: 'iowait 35%，写入集中在 /var/log/app.log', is_untrusted: true }
      ],
      evidence_tree: [{ id: 'io', label: 'I/O 异常诊断', value: 'iowait 35%', children: [{ id: 'log', label: '写入热点', value: '/var/log/app.log' }] }],
      safe_actions: ['定位日志写入进程', '调整日志级别', '配置 logrotate'],
      dangerous_actions_rejected: [{ action: '直接 truncate 正在写入的数据库日志', reason: '可能破坏文件句柄和审计连续性', rule_id: 'LOG002' }]
    }
  }

  if (problemType === 'config_drift') {
    return {
      ...base,
      summary: '检测到配置漂移，涉及 sshd_config 等高风险配置，建议先生成 diff 与审批单，不自动覆盖。',
      root_cause_candidates: [
        { cause: '关键配置文件与基线 hash 不一致', confidence: 0.84, evidence: ['/etc/ssh/sshd_config hash 变化', 'config.diff 显示 PermitRootLogin 被修改'], evidence_refs: ['ev_cfg_001'] }
      ],
      evidence_chain: [
        { id: 'ev_cfg_001', source_tool: 'config.diff', title: '发现配置漂移', detail: 'PermitRootLogin yes 与基线不一致', is_untrusted: true }
      ],
      evidence_tree: [{ id: 'cfg', label: '配置漂移检测', value: '异常', children: [{ id: 'sshd', label: 'sshd_config', value: 'PermitRootLogin 变化' }] }],
      safe_actions: ['导出 diff 报告', '提交管理员审批后恢复配置'],
      dangerous_actions_rejected: [{ action: '未经确认直接覆盖 /etc/ssh/sshd_config', reason: '可能导致远程访问中断', rule_id: 'CFG001' }]
    }
  }

  return {
    ...base,
    summary: description || '根分区占用过高，主要由应用日志持续增长导致；数据库 binlog 属高风险数据，不应直接删除。',
    root_cause_candidates: [
      { cause: '/var/log/app.log 持续增长导致根分区占用过高', confidence: 0.87, evidence: ['根分区使用率 92%', '/var/log/app.log 占用 18GB', '未发现数据库进程持有该文件'], evidence_refs: ['ev_disk_001', 'ev_disk_002'] }
    ],
    evidence_chain: [
      { id: 'ev_disk_001', source_tool: 'disk.usage', title: '根分区使用率过高', detail: '根分区使用率 92%', is_untrusted: true },
      { id: 'ev_disk_002', source_tool: 'disk.large_files', title: '发现大日志', detail: '/var/log/app.log 18GB', is_untrusted: true }
    ],
    evidence_tree: [
      { id: 'disk', label: '磁盘满诊断', value: '92%', children: [
        { id: 'df', label: 'df -hT', value: 'root 92%' },
        { id: 'du', label: '大文件扫描', value: '/var/log/app.log 18GB' },
        { id: 'lsof', label: '占用检查', value: '未发现危险占用' }
      ] }
    ],
    safe_actions: ['压缩并轮转日志', '设置 logrotate 策略', '保留审计记录'],
    dangerous_actions_rejected: [{ action: '直接 rm 删除数据库 binlog', reason: '可能破坏数据库恢复链路', rule_id: 'DBLOG001' }]
  }
}
