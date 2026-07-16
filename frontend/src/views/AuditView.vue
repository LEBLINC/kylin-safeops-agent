<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageSection from '@/components/PageSection.vue'
import HashChainViewer from '@/components/HashChainViewer.vue'
import StatusTag from '@/components/StatusTag.vue'
import { useAuditStore } from '@/stores/audit'
import { isMockEnabled } from '@/api/mock-flag'
import type { AuditTrace } from '@/types/audit'
import { prettyJson } from '@/utils/format'
import { formatTime } from '@/utils/time'

const audit = useAuditStore()
const selectedTrace = ref('')

onMounted(async () => {
  await audit.loadTraces(1)
  if (audit.traces[0]) {
    selectedTrace.value = audit.traces[0].trace_id
    await selectTrace(selectedTrace.value)
  }
})

async function selectTrace(traceId: string) {
  selectedTrace.value = traceId
  await audit.loadDetail(traceId)
  await audit.verify(traceId)
}

function handleTraceRowClick(row: AuditTrace) {
  selectTrace(row.trace_id)
}

function handlePageChange(page: number) {
  audit.loadTraces(page)
}

function formatPayloadVal(val: unknown): string {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

function phaseTagType(phase: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  const m: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'primary'> = {
    user_input: 'info',
    INTENT_PARSED: 'primary',
    EXECUTING: 'warning',
    EXECUTED: 'success',
    policy_verdict: 'warning',
    FINISHED: 'success',
    REJECTED: 'danger'
  }
  return m[phase] || 'info'
}
</script>

<template>
  <div class="ks-page">
    <div class="audit-main">
      <!-- 左：Trace 列表 -->
      <PageSection title="Trace 列表">
        <el-table :data="audit.traces" @row-click="handleTraceRowClick" highlight-current-row stripe size="small">
          <el-table-column label="Trace ID" width="200">
            <template #default="{ row }">
              <el-tooltip :content="row.trace_id" placement="top" :show-after="500">
                <span class="trace-id-cell">{{ row.trace_id }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column prop="first_user_intent" label="意图" min-width="120" show-overflow-tooltip />
          <el-table-column label="终态" width="100">
            <template #default="{ row }">
              <StatusTag :status="row.state" />
            </template>
          </el-table-column>
          <el-table-column prop="record_count" label="记录数" width="70" align="center" />
        </el-table>
        <div v-if="audit.total > audit.pageSize" class="audit-pagination">
          <el-pagination
            background
            layout="prev, pager, next"
            :total="audit.total"
            :page-size="audit.pageSize"
            :current-page="audit.page"
            @current-change="handlePageChange"
            size="small"
          />
        </div>
      </PageSection>

      <!-- 右：审计记录详情 -->
      <PageSection title="审计记录详情">
        <el-table :data="audit.records" size="small">
          <el-table-column prop="seq" label="#" width="50" align="center" />
          <el-table-column label="阶段" width="140">
            <template #default="{ row }">
              <el-tag size="small" :type="phaseTagType(row.phase)" effect="dark">{{ row.phase }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="payload" min-width="260">
            <template #default="{ row }">
              <div class="payload-table">
                <div v-for="(val, key) in row.payload" :key="key" class="payload-row">
                  <span class="payload-key">{{ key }}</span>
                  <span class="payload-val">{{ formatPayloadVal(val) }}</span>
                </div>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </PageSection>
    </div>

    <el-alert
      v-if="!isMockEnabled() && audit.traces.length === 0"
      type="info"
      show-icon
      :closable="false"
      title="暂无审计记录"
      description="当前无审计 trace 数据，发起一次智能对话后即可在此回溯。"
    />

    <HashChainViewer
      v-if="audit.verifyResult"
      :valid="audit.verifyResult.valid"
      :records="audit.verifyResult.records"
    />
  </div>
</template>

<style scoped>
.audit-main {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: start;
}
.audit-pagination {
  display: flex;
  justify-content: center;
  margin-top: 12px;
}
.trace-id-cell {
  display: block;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: monospace;
  font-size: 12px;
  cursor: default;
}
.payload-table {
  display: grid;
  gap: 2px;
}
.payload-row {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 6px;
  align-items: baseline;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
}
.payload-row:nth-child(even) {
  background: #f8fafc;
}
.payload-key {
  color: #64748b;
  font-weight: 600;
  font-family: monospace;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.payload-val {
  color: #1e293b;
  word-break: break-all;
}
</style>
