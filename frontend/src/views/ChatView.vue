<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'
import AgentTimeline from '@/components/AgentTimeline.vue'
import SecurityDecisionCard from '@/components/SecurityDecisionCard.vue'
import ToolCallCard from '@/components/ToolCallCard.vue'
import ApprovalCard from '@/components/ApprovalCard.vue'
import HashChainViewer from '@/components/HashChainViewer.vue'
import EvidenceTree from '@/components/EvidenceTree.vue'
import EmptyState from '@/components/EmptyState.vue'
import RiskTag from '@/components/RiskTag.vue'
import { canRoleApprove, useChatStore } from '@/stores/chat'
import type { PerToolVerdict, PolicyVerdict } from '@/types/policy'

/**
 * ChatView.vue
 *
 * 智能对话主页面，是整个系统最重要的演示入口。
 *
 * 页面结构：
 * 1. 左侧：多会话列表，可新建、搜索、重命名、删除；
 * 2. 中间：聊天窗口，展示用户消息、AI 打字机回复、对话内审批卡片；
 * 3. 右侧：Agent 执行链路、安全裁决、工具结果、RCA 证据链、审计哈希链。
 *
 * 核心数据流：
 * 用户点击发送
 *   → submit()
 *   → chatStore.sendMessage()
 *   → api/chat.ts sendMessage()
 *   → 真实后端或 api/mock.ts 返回 trace_id
 *   → connectChatStream() 持续接收 StreamEvent
 *   → chatStore.addEvent() 分类入库
 *   → 页面自动刷新。
 *
 * 重要交互约束：
 * - 审批操作必须出现在中间聊天区，不放在右侧；
 * - 右侧只展示证据和链路，不承载审批按钮；
 * - 左侧、中间、右侧三个区域各自独立滚动，互不影响；
 * - 当前 stream.py 没有 token 级事件，AI 打字机效果由前端基于 verified.summary 实现。
 */
const chat = useChatStore()

/** 输入框内容。默认填一个常用演示问题，方便打开页面直接测试。 */
const input = ref('帮我看看磁盘为什么快满了，并给出安全处理建议')
/** 左侧会话搜索输入框。 */
const searchKeyword = ref('')
/** 中间消息列表 DOM，用于消息新增后自动滚到底部。 */
const messageBox = ref<HTMLElement | null>(null)

onMounted(() => {
  chat.initSessions()
})

/** 当前 trace 最近一次 policy_verdict 事件，用于右侧安全裁决卡展示。 */
const latestPolicyData = computed(() => {
  const event = [...chat.currentEvents].reverse().find(item => item.type === 'policy_verdict')
  return event?.data as { verdict?: PolicyVerdict; per_tool?: PerToolVerdict[] } | undefined
})

/** 整批安全裁决。 */
const latestVerdict = computed(() => latestPolicyData.value?.verdict)
/** 逐工具裁决列表。 */
const perToolVerdicts = computed(() => latestPolicyData.value?.per_tool || [])
/** 当前 trace 的工具结果。 */
const toolResults = computed(() => chat.currentToolResults)

/**
 * 当前内联审批数据。
 * 注意：它会被渲染到中间聊天区的某条 system 消息中，右侧不再展示审批操作按钮。
 */
const inlineApproval = computed(() => chat.currentApproval)

/** 当前用户角色是否可以批准本批计划。 */
const canApproveCurrentBatch = computed(() => {
  const approval = inlineApproval.value
  if (!approval) return false
  return canRoleApprove(chat.currentUserRole, approval.approval_role)
})

/** 消息列表变化后自动滚动到底部。 */
watch(
  () => chat.currentMessages.map(item => `${item.id}:${item.content}:${item.status}:${item.approval?.status}`).join('|'),
  async () => {
    await nextTick()
    if (messageBox.value) messageBox.value.scrollTop = messageBox.value.scrollHeight
  }
)

/**
 * 发送按钮入口。
 *
 * 这里只做输入校验和调用 store：
 * 1. 页面不直接请求 axios；
 * 2. 页面不直接拼 Mock 数据；
 * 3. 页面不直接操作 EventSource；
 * 4. 真实后端 / Mock 由 api 层统一决定。
 */
async function submit() {
  const content = input.value.trim()
  if (!content) return
  input.value = ''
  await chat.sendMessage(content)
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter') return
  if (event.shiftKey) return
  event.preventDefault()
  submit()
}

/** 新建会话。 */
async function createSession() {
  await chat.createLocalSession('新会话')
}

/** 搜索会话。 */
function onSearch(value: string) {
  chat.searchSessions(value)
}

/** 重命名会话。 */
async function renameSession(sessionId: string, oldTitle: string) {
  try {
    const result = await ElMessageBox.prompt('请输入新的会话名称', '重命名会话', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: oldTitle,
      inputValidator: (value: string) => Boolean(value.trim()) || '会话名称不能为空'
    })
    await chat.renameSession(sessionId, result.value)
    ElMessage.success('会话已重命名')
  } catch {
    // 用户取消时不提示错误。
  }
}

/** 删除会话。 */
async function deleteSession(sessionId: string) {
  try {
    await ElMessageBox.confirm('确认删除该会话吗？删除后本地消息记录也会移除。', '删除会话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await chat.deleteSession(sessionId)
    ElMessage.success('会话已删除')
  } catch {
    // 用户取消时不提示错误。
  }
}

/**
 * 批准当前批次的原子计划。
 * 使用传入的 traceId，禁止默认使用 activeTraceId，确保多审批卡正确路由。
 */
async function approveBatch(traceId: string) {
  await chat.approveInlinePlan(traceId, '确认执行本批原子计划')
}

/**
 * 拒绝当前批次的原子计划。
 * 使用传入的 traceId。
 */
async function rejectBatch(traceId: string) {
  try {
    const result = await ElMessageBox.prompt('请输入拒绝原因，可留空', '拒绝整批计划', {
      confirmButtonText: '确认拒绝',
      cancelButtonText: '取消',
      inputValue: '风险较高，拒绝执行'
    })
    await chat.rejectInlinePlan(traceId, result.value || '拒绝执行本批计划')
  } catch {
    // 用户取消时不提示错误。
  }
}

/** 权限不足时，申请转管理员审批。使用传入 traceId。 */
async function escalateBatch(traceId: string) {
  await chat.escalateInlinePlan(traceId, '当前用户权限不足，申请管理员审批')
  ElMessage.success('已提交管理员审批')
}
</script>

<template>
  <div class="ks-page chat-page">
    <PageHeader title="智能对话" subtitle="自然语言运维入口，所有工具调用均经过策略校验与审计" />

    <div class="chat-layout">
      <PageSection title="会话列表" class="sessions">
        <div class="session-toolbar">
          <el-input
            v-model="searchKeyword"
            clearable
            size="small"
            placeholder="搜索会话..."
            @input="onSearch"
          />
          <el-button type="primary" size="small" @click="createSession">新建</el-button>
        </div>

        <div class="session-list">
          <div
            v-for="session in chat.filteredSessions"
            :key="session.session_id"
            class="session"
            :class="{ active: chat.currentSessionId === session.session_id }"
            @click="chat.switchSession(session.session_id)"
          >
            <div class="session-main">
              <strong>{{ session.title }}</strong>
              <el-dropdown trigger="click" @command="(cmd: string) => cmd === 'rename' ? renameSession(session.session_id, session.title) : deleteSession(session.session_id)">
                <span class="session-more" @click.stop>⋯</span>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="rename">重命名</el-dropdown-item>
                    <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
            <span>{{ session.last_message || session.last_trace_id || '暂无消息' }}</span>
            <div class="session-tags" v-if="session.risk_level || session.pending_approval_count">
              <RiskTag v-if="session.risk_level" :level="session.risk_level" />
              <el-tag v-if="session.pending_approval_count" type="warning" effect="dark" size="small">
                待审批 {{ session.pending_approval_count }}
              </el-tag>
            </div>
          </div>

          <EmptyState v-if="!chat.filteredSessions.length" title="没有匹配会话" description="换个关键词试试" />
        </div>
      </PageSection>

      <PageSection title="对话窗口" class="conversation">
        <div ref="messageBox" class="messages">
          <div
            v-for="message in chat.currentMessages"
            :key="message.id"
            class="message"
            :class="message.role"
          >
            <div class="bubble" :class="{ approval: Boolean(message.approval), streaming: message.status === 'streaming' }">
              <ApprovalCard
                v-if="message.approval"
                :inline="message.approval"
                :current-role="chat.currentUserRole"
                :can-approve="canApproveCurrentBatch"
                @approve="(traceId: string) => approveBatch(traceId)"
                @reject="(traceId: string) => rejectBatch(traceId)"
                @escalate="(traceId: string) => escalateBatch(traceId)"
              />
              <template v-else>
                {{ message.content }}<span v-if="message.status === 'streaming'" class="typing-cursor">▌</span>
              </template>
            </div>
          </div>
          <EmptyState v-if="!chat.currentMessages.length" title="开始一次安全运维对话" description="例如：帮我看看磁盘为什么快满了" />
        </div>

        <div class="input-area">
          <div class="composer-shell">
            <el-input
              v-model="input"
              type="textarea"
              :rows="3"
              resize="none"
              placeholder="输入运维需求，例如：检查根分区占用并给出安全处理建议"
              @keydown="handleComposerKeydown"
            />
            <div class="composer-overlay">
              <span class="ks-muted">Enter 发送 · Shift + Enter 换行 · {{ chat.currentUser || '未知' }}（{{ chat.currentUserRole }}）</span>
              <el-button type="primary" :loading="chat.loading" @click="submit">发送</el-button>
            </div>
          </div>
        </div>
      </PageSection>

      <div class="right-panel">
        <PageSection title="Agent 执行链路">
          <AgentTimeline :events="chat.currentEvents" />
        </PageSection>

        <SecurityDecisionCard
          v-if="latestVerdict"
          :verdict="latestVerdict"
          :per-tool="perToolVerdicts"
        />

        <PageSection title="工具结果" v-if="toolResults.length">
          <div class="tool-result-stack">
            <ToolCallCard v-for="(result, index) in toolResults" :key="`${result.tool}-${index}`" :result="result" />
          </div>
        </PageSection>

        <PageSection title="RCA 证据链" v-if="chat.currentRcaReport">
          <p class="rca-summary">{{ chat.currentRcaReport.summary }}</p>
          <EvidenceTree :evidence="chat.currentRcaReport.evidence_chain" />
        </PageSection>

        <HashChainViewer v-if="chat.currentAuditNodes.length" :nodes="chat.currentAuditNodes" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-page {
  height: calc(100vh - 96px);
  min-height: 680px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.chat-layout {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 420px;
  gap: 16px;
  align-items: stretch;
  overflow: hidden;
}
.sessions,
.conversation {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.session-toolbar {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  margin-bottom: 12px;
}
.session-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}
.session {
  padding: 12px;
  border-radius: 12px;
  border: 1px solid var(--ks-border);
  margin-bottom: 10px;
  cursor: pointer;
  background: rgba(255,255,255,0.84);
  transition: transform 160ms ease, background 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
}
.session:hover { background: linear-gradient(135deg, rgba(239,246,255,0.94), rgba(255,255,255,0.92)); transform: translateX(3px); box-shadow: 0 10px 24px rgba(37,99,235,0.08); }
.session.active { background: linear-gradient(135deg, rgba(219,234,254,0.92), rgba(255,255,255,0.94)); border-color: rgba(37, 99, 235, 0.34); }
.session-main { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.session-more { color: var(--ks-text-muted); padding: 2px 6px; border-radius: 8px; }
.session-more:hover { color: var(--ks-primary); background: #eef4ff; }
.session span { display: block; margin-top: 6px; color: var(--ks-text-muted); font-size: 12px; line-height: 1.4; }
.session-tags { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }
.conversation :deep(.section-header) { flex: 0 0 auto; }
.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 8px;
}
.message { display: flex; margin: 14px 0; }
.message.user { justify-content: flex-end; }
.message.system { justify-content: center; }
.bubble {
  max-width: 78%;
  line-height: 1.75;
  padding: 14px 16px;
  border-radius: 18px;
  white-space: pre-wrap;
  background: linear-gradient(135deg, rgba(248,250,252,0.98), rgba(255,255,255,0.98));
  border: 1px solid var(--ks-border);
  box-shadow: 0 10px 24px rgba(15,23,42,0.05);
  position: relative;
}
.bubble.approval {
  width: min(720px, 96%);
  max-width: 96%;
  padding: 0;
  border: none;
  background: transparent;
  box-shadow: none;
}
.message.user .bubble {
  color: #ffffff;
  background: linear-gradient(135deg, #2563eb, #06b6d4);
  border-color: transparent;
  box-shadow: 0 16px 28px rgba(37,99,235,0.22);
}
.message.system .bubble:not(.approval) {
  background: linear-gradient(135deg, rgba(255,247,237,0.98), rgba(255,255,255,0.98));
  border-color: rgba(245, 158, 11, 0.35);
}
.message.assistant .bubble.streaming {
  background: linear-gradient(135deg, rgba(239,246,255,0.98), rgba(255,255,255,0.98), rgba(236,254,255,0.98));
}
.message.assistant .bubble.streaming::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.65), transparent);
  transform: translateX(-100%);
  animation: shimmer 1.8s infinite;
  pointer-events: none;
}
.typing-cursor { display: inline-block; color: var(--ks-primary); margin-left: 2px; animation: blink 1s steps(2, start) infinite; }
@keyframes blink { 50% { opacity: 0; } }
@keyframes shimmer { 100% { transform: translateX(100%); } }
.input-area {
  flex: 0 0 auto;
  padding-top: 14px;
}
.composer-shell {
  position: relative;
  border: 1px solid rgba(37,99,235,0.18);
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(239,246,255,0.86), rgba(236,254,255,0.78));
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.9), 0 12px 28px rgba(37,99,235,0.08);
  overflow: hidden;
}
.composer-shell :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none;
  background: rgba(255,255,255,0.94);
  border-radius: 20px;
  padding: 18px 132px 46px 18px;
  line-height: 1.7;
  min-height: 128px;
}
.composer-shell :deep(.el-textarea__inner:focus) {
  box-shadow: inset 0 0 0 1px rgba(37,99,235,0.16);
}
.composer-overlay {
  position: absolute;
  left: 18px;
  right: 14px;
  bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  pointer-events: none;
}
.composer-overlay .el-button {
  pointer-events: auto;
  border-radius: 12px;
  min-width: 64px;
}
.composer-overlay .ks-muted {
  font-size: 12px;
  line-height: 1.4;
  max-width: calc(100% - 92px);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tool-result-stack {
  display: grid;
  gap: 16px;
}
.right-panel {
  min-height: 0;
  height: 100%;
  overflow-y: auto;
  display: grid;
  gap: 16px;
  align-content: start;
  padding-right: 4px;
}
.rca-summary { color: var(--ks-text-muted); line-height: 1.6; margin: 0 0 12px; }
@media (max-width: 1300px) {
  .chat-page { height: auto; overflow: visible; }
  .chat-layout { grid-template-columns: 1fr; overflow: visible; }
  .sessions,
  .conversation,
  .right-panel { height: auto; max-height: none; overflow: visible; }
  .messages { max-height: 520px; }
}
</style>
