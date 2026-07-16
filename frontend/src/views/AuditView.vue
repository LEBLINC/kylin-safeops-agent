<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageSection from '@/components/PageSection.vue'
import HashChainViewer from '@/components/HashChainViewer.vue'
import StatusTag from '@/components/StatusTag.vue'
import { useAuditStore } from '@/stores/audit'
import { isMockEnabled } from '@/api/mock-flag'
import type { AuditRecord, AuditTrace } from '@/types/audit'
import { prettyJson } from '@/utils/format'
import { formatTime } from '@/utils/time'

const audit = useAuditStore()
const selectedTrace = ref('')

const selectedSummary = computed(() =>
  audit.traces.find(item => item.trace_id === selectedTrace.value)
)

const phaseLabels: Record<string, string> = {
  RECEIVED: '接收请求',
  user_input: '用户输入',
  INTENT_PARSED: '意图解析',
  CONTEXT_COLLECTED: '上下文收集',
  PLAN_GENERATED: '生成计划',
  POLICY_CHECKED: '策略检查',
  policy_verdict: '策略裁决',
  WAIT_APPROVAL: '等待审批',
  APPROVED: '审批通过',
  EXECUTING: '开始执行',
  EXECUTED: '执行完成',
  VERIFYING: '结果校验',
  VERIFIED: '校验完成',
  FINISHED: '链路完成',
  REJECTED: '已拒绝',
  FAILED: '执行失败'
}

const payloadLabels: Record<string, string> = {
  actor: '执行主体',
  user: '用户',
  roles: '角色',
  user_intent: '用户意图',
  risk_level: '风险等级',
  observations: '观测结果',
  tool_plan: '工具计划',
  approval_required: '需要审批',
  approval_role: '审批角色',
  decision: '策略裁决',
  denied_tools: '被拒绝工具',
  tool: '工具',
  tools: '工具列表',
  args: '调用参数',
  exit_code: '退出码',
  executed: '是否执行',
  verify_result: '校验结果',
  result: '执行结果',
  error: '错误信息'
}

onMounted(async () => {
  await loadPage(1)
})

async function loadPage(page: number) {
  await audit.loadTraces(page)
  const first = audit.traces[0]
  if (first) {
    await selectTrace(first.trace_id)
  } else {
    selectedTrace.value = ''
    audit.records = []
    audit.verifyResult = null
  }
}

async function selectTrace(traceId: string) {
  selectedTrace.value = traceId
  await audit.loadDetail(traceId)
}

function handleTraceRowClick(row: AuditTrace) {
  if (row.trace_id !== selectedTrace.value) selectTrace(row.trace_id)
}

function handlePageChange(page: number) {
  loadPage(page)
}

function traceRowClassName({ row }: { row: AuditTrace }) {
  return row.trace_id === selectedTrace.value ? 'is-selected-trace' : ''
}

function phaseLabel(phase: string) {
  return phaseLabels[phase] || phase
}

function phaseTagType(phase: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  const map: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'primary'> = {
    RECEIVED: 'info',
    user_input: 'info',
    INTENT_PARSED: 'primary',
    CONTEXT_COLLECTED: 'info',
    PLAN_GENERATED: 'primary',
    POLICY_CHECKED: 'warning',
    policy_verdict: 'warning',
    WAIT_APPROVAL: 'warning',
    APPROVED: 'success',
    EXECUTING: 'warning',
    EXECUTED: 'success',
    VERIFYING: 'warning',
    VERIFIED: 'success',
    FINISHED: 'success',
    REJECTED: 'danger',
    FAILED: 'danger'
  }
  return map[phase] || 'info'
}

function payloadEntries(payload: Record<string, unknown>) {
  return Object.entries(payload)
}

function payloadLabel(key: string) {
  return payloadLabels[key] || key
}

function isComplex(value: unknown) {
  return typeof value === 'object' && value !== null
}

function formatPrimitive(value: unknown) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (value === '') return '空字符串'
  return String(value)
}

function summarizePayload(record: AuditRecord) {
  const payload = record.payload

  if (typeof payload.user_intent === 'string') {
    return `用户意图：${payload.user_intent}`
  }

  if (Array.isArray(payload.tool_plan)) {
    return `生成 ${payload.tool_plan.length} 个工具步骤，展开可查看完整计划。`
  }

  if (Array.isArray(payload.observations)) {
    return payload.observations.length
      ? `已收集 ${payload.observations.length} 项观测结果。`
      : '本阶段未产生观测结果。'
  }

  if (payload.decision !== undefined || payload.risk_level !== undefined) {
    const parts = []
    if (payload.decision !== undefined) parts.push(`裁决 ${formatPrimitive(payload.decision)}`)
    if (payload.risk_level !== undefined) parts.push(`风险 ${formatPrimitive(payload.risk_level)}`)
    if (payload.approval_required !== undefined) {
      parts.push(`审批 ${formatPrimitive(payload.approval_required)}`)
    }
    return parts.join(' · ')
  }

  if (Array.isArray(payload.denied_tools)) {
    return `已拒绝 ${payload.denied_tools.length} 个工具：${payload.denied_tools.join('、') || '—'}`
  }

  if (typeof payload.tool === 'string') {
    return `工具：${payload.tool}`
  }

  const count = Object.keys(payload).length
  return count ? `包含 ${count} 个结构化审计字段。` : '该阶段没有附加字段。'
}

function shortTraceId(traceId: string) {
  if (traceId.length <= 20) return traceId
  return `${traceId.slice(0, 10)}…${traceId.slice(-8)}`
}
</script>

<template>
  <div class="ks-page audit-page">
    <div class="audit-main">
      <PageSection
        title="Trace 列表"
        :subtitle="`按最近更新时间排序，共 ${audit.total} 条审计链路`"
      >
        <template #extra>
          <el-tag type="info" effect="plain">第 {{ audit.page }} 页</el-tag>
        </template>

        <el-table
          v-loading="audit.loading"
          :data="audit.traces"
          :row-class-name="traceRowClassName"
          @row-click="handleTraceRowClick"
          stripe
          size="small"
        >
          <el-table-column label="Trace ID" width="180">
            <template #default="{ row }">
              <el-tooltip :content="row.trace_id" placement="top" :show-after="500">
                <code class="trace-id-cell">{{ shortTraceId(row.trace_id) }}</code>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column prop="first_user_intent" label="意图" min-width="210" show-overflow-tooltip />
          <el-table-column label="终态" width="92">
            <template #default="{ row }">
              <StatusTag :status="row.state" />
            </template>
          </el-table-column>
          <el-table-column prop="record_count" label="记录" width="64" align="center" />
        </el-table>

        <div v-if="audit.total > audit.pageSize" class="audit-pagination">
          <el-pagination
            background
            layout="prev, pager, next"
            :total="audit.total"
            :page-size="audit.pageSize"
            :current-page="audit.page"
            size="small"
            @current-change="handlePageChange"
          />
        </div>
      </PageSection>

      <PageSection
        title="审计记录详情"
        subtitle="按状态机阶段展示结构化审计摘要；原始字段可按需展开"
      >
        <template #extra>
          <StatusTag v-if="selectedSummary" :status="selectedSummary.state" />
        </template>

        <div v-if="selectedSummary" class="trace-context">
          <div>
            <span>当前 Trace</span>
            <code :title="selectedSummary.trace_id">{{ selectedSummary.trace_id }}</code>
          </div>
          <div>
            <span>首次意图</span>
            <strong>{{ selectedSummary.first_user_intent || '—' }}</strong>
          </div>
          <div>
            <span>记录数</span>
            <strong>{{ selectedSummary.record_count }}</strong>
          </div>
        </div>

        <el-alert
          v-if="audit.detailError"
          type="error"
          show-icon
          :closable="false"
          title="审计详情加载失败"
          :description="audit.detailError"
        />

        <div v-loading="audit.detailLoading" class="event-panel">
          <div v-if="audit.records.length" class="event-list">
            <article v-for="record in audit.records" :key="record.seq" class="audit-event">
              <div class="event-rail">
                <span>{{ record.seq }}</span>
                <i />
              </div>

              <div class="event-card">
                <header class="event-head">
                  <div class="phase-wrap">
                    <el-tag size="small" :type="phaseTagType(record.phase)" effect="dark">
                      {{ phaseLabel(record.phase) }}
                    </el-tag>
                    <code>{{ record.phase }}</code>
                  </div>
                  <time>{{ formatTime(record.created_at) }}</time>
                </header>

                <p class="payload-summary">{{ summarizePayload(record) }}</p>

                <details v-if="Object.keys(record.payload).length" class="payload-details">
                  <summary>查看结构化字段（{{ Object.keys(record.payload).length }}）</summary>
                  <div class="payload-fields">
                    <div
                      v-for="([key, value]) in payloadEntries(record.payload)"
                      :key="key"
                      class="payload-field"
                    >
                      <div class="payload-name">
                        <strong>{{ payloadLabel(key) }}</strong>
                        <code>{{ key }}</code>
                      </div>
                      <pre v-if="isComplex(value)">{{ prettyJson(value) }}</pre>
                      <span v-else>{{ formatPrimitive(value) }}</span>
                    </div>
                  </div>
                </details>
              </div>
            </article>
          </div>

          <div v-else-if="!audit.detailLoading" class="detail-empty">
            请选择左侧 Trace 查看审计阶段与结构化字段。
          </div>
        </div>
      </PageSection>
    </div>

    <el-alert
      v-if="audit.error"
      type="error"
      show-icon
      :closable="false"
      title="审计列表加载失败"
      :description="audit.error"
    />

    <el-alert
      v-else-if="!isMockEnabled() && audit.traces.length === 0"
      type="info"
      show-icon
      :closable="false"
      title="暂无审计记录"
      description="当前无审计 Trace 数据，发起一次智能对话后即可在此回溯。"
    />

    <HashChainViewer
      v-if="selectedTrace"
      :valid="audit.verifyResult?.valid"
      :record-count="audit.verifyResult?.record_count"
      :broken-seq="audit.verifyResult?.broken_seq"
      :reason="audit.verifyResult?.reason"
      :verifying="audit.verifying"
      show-verify-action
      @verify="audit.verify(selectedTrace)"
    />
  </div>
</template>

<style scoped>
.audit-page {
  display: grid;
  gap: 18px;
}

.audit-main {
  display: grid;
  grid-template-columns: minmax(520px, 0.9fr) minmax(640px, 1.18fr);
  gap: 16px;
  align-items: start;
}

.audit-pagination {
  display: flex;
  justify-content: center;
  margin-top: 14px;
}

.trace-id-cell {
  display: block;
  max-width: 160px;
  overflow: hidden;
  color: var(--ks-text);
  font-family: monospace;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.el-table .is-selected-trace > td.el-table__cell) {
  background: rgba(37, 99, 235, 0.1) !important;
}

.trace-context {
  margin-bottom: 14px;
  padding: 12px 14px;
  display: grid;
  grid-template-columns: minmax(210px, 1fr) minmax(220px, 1.45fr) 72px;
  gap: 14px;
  border: 1px solid var(--ks-border);
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.55);
}

.trace-context > div {
  min-width: 0;
}

.trace-context span,
.trace-context code,
.trace-context strong {
  display: block;
}

.trace-context span {
  margin-bottom: 5px;
  color: var(--ks-text-muted);
  font-size: 10px;
}

.trace-context code,
.trace-context strong {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-panel {
  min-height: 360px;
}

.event-list {
  max-height: 590px;
  padding-right: 6px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.audit-event {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 10px;
}

.event-rail {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.event-rail span {
  position: relative;
  z-index: 1;
  width: 28px;
  height: 28px;
  border: 1px solid rgba(37, 99, 235, 0.18);
  border-radius: 9px;
  display: grid;
  place-items: center;
  color: var(--ks-primary);
  background: #eef4ff;
  font-size: 11px;
  font-weight: 800;
}

.event-rail i {
  width: 1px;
  min-height: 34px;
  flex: 1;
  background: linear-gradient(var(--ks-border), transparent);
}

.audit-event:last-child .event-rail i {
  display: none;
}

.event-card {
  min-width: 0;
  margin-bottom: 12px;
  padding: 13px 14px;
  border: 1px solid var(--ks-border);
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.6);
}

.event-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.phase-wrap {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.phase-wrap code {
  overflow: hidden;
  color: var(--ks-text-muted);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-head time {
  flex: 0 0 auto;
  color: var(--ks-text-muted);
  font-size: 11px;
}

.payload-summary {
  margin: 10px 0 0;
  color: var(--ks-text);
  font-size: 12px;
  line-height: 1.6;
}

.payload-details {
  margin-top: 10px;
  border-top: 1px dashed var(--ks-border);
}

.payload-details summary {
  padding-top: 10px;
  color: var(--ks-primary);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  user-select: none;
}

.payload-fields {
  margin-top: 10px;
  display: grid;
  gap: 8px;
}

.payload-field {
  padding: 9px 10px;
  display: grid;
  grid-template-columns: 126px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  border-radius: 10px;
  background: rgba(241, 245, 249, 0.72);
}

.payload-name {
  min-width: 0;
}

.payload-name strong,
.payload-name code {
  display: block;
}

.payload-name strong {
  font-size: 11px;
}

.payload-name code {
  margin-top: 3px;
  overflow: hidden;
  color: var(--ks-text-muted);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.payload-field > span {
  color: var(--ks-text);
  font-size: 12px;
  line-height: 1.55;
  word-break: break-word;
}

.payload-field pre {
  max-height: 220px;
  margin: 0;
  padding: 9px 10px;
  overflow: auto;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 9px;
  color: #334155;
  background: rgba(255, 255, 255, 0.72);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.detail-empty {
  min-height: 320px;
  display: grid;
  place-items: center;
  color: var(--ks-text-muted);
  font-size: 13px;
}

@media (max-width: 1280px) {
  .audit-main {
    grid-template-columns: minmax(0, 1fr);
  }

  .event-list {
    max-height: none;
  }
}

@media (max-width: 720px) {
  .trace-context {
    grid-template-columns: minmax(0, 1fr);
  }

  .event-head {
    align-items: flex-start;
    flex-direction: column;
    gap: 7px;
  }

  .payload-field {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
