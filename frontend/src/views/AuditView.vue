<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'
import HashChainViewer from '@/components/HashChainViewer.vue'
import StatusTag from '@/components/StatusTag.vue'
import { useAuditStore } from '@/stores/audit'
import { isMockEnabled } from '@/api/mock'
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
</script>

<template>
  <div class="ks-page">
    <PageHeader title="审计日志" subtitle="按 trace_id 回溯完整链路，并校验哈希链防篡改" />

    <div class="audit-top">
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

      <HashChainViewer
        v-if="audit.verifyResult"
        :valid="audit.verifyResult.valid"
        :records="audit.verifyResult.records"
      />
    </div>

    <el-alert
      v-if="!isMockEnabled() && audit.traces.length === 0"
      type="info"
      show-icon
      :closable="false"
      title="暂无审计记录"
      description="当前无审计 trace 数据，发起一次智能对话后即可在此回溯。"
    />

    <PageSection title="审计记录详情">
      <el-table :data="audit.records" size="small">
        <el-table-column prop="seq" label="#" width="50" align="center" />
        <el-table-column prop="phase" label="阶段" width="150">
          <template #default="{ row }">
            <el-tag size="small" type="info" effect="plain">{{ row.phase }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="payload" min-width="200">
          <template #default="{ row }">
            <pre class="payload-pre">{{ prettyJson(row.payload) }}</pre>
          </template>
        </el-table-column>
      </el-table>
    </PageSection>
  </div>
</template>

<style scoped>
.audit-top {
  display: grid;
  grid-template-columns: 3fr 2fr;
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
.payload-pre {
  margin: 0;
  padding: 4px 0;
  white-space: pre-wrap;
  max-height: 100px;
  overflow: auto;
  font-size: 12px;
  color: #475569;
  background: transparent;
}
</style>
