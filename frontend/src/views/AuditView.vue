<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'
import HashChainViewer from '@/components/HashChainViewer.vue'
import StatusTag from '@/components/StatusTag.vue'
import RiskTag from '@/components/RiskTag.vue'
import { useAuditStore } from '@/stores/audit'
import { isMockEnabled } from '@/api/mock'
import type { AuditTrace } from '@/types/audit'
import { prettyJson } from '@/utils/format'
import { formatTime } from '@/utils/time'

/**
 * AuditView.vue
 *
 * 审计日志页面。
 *
 * 页面作用：
 * - 按 trace_id 查看一次完整 Agent 请求的审计记录；
 * - 展示用户输入、策略裁决、工具调用、审批、执行结果等结构化记录；
 * - 调用哈希链校验接口，展示审计链是否完整。
 *
 * 数据来源：
 * - useAuditStore().traces：审计 trace 列表；
 * - useAuditStore().records：当前 trace 的审计记录；
 * - useAuditStore().verifyResult：哈希链校验结果。
 *
 * 与 stream.py 的关系：
 * - stream.py 只实时推 audit_appended 的 seq/curr_hash；
 * - 本页面主要使用 /api/audit/* REST 接口做事后查询。
 */
const audit = useAuditStore()

/** 当前选中的 trace_id。用于表格点击后加载详情和哈希链。 */
const selectedTrace = ref('')

/**
 * 页面初始化流程。
 *
 * 1. 加载 trace 列表；
 * 2. 如果列表不为空，默认选中第一条；
 * 3. 自动加载第一条的详情和哈希链校验结果。
 */
onMounted(async () => {
  await audit.loadTraces()
  if (audit.traces[0]) {
    selectedTrace.value = audit.traces[0].trace_id
    await selectTrace(selectedTrace.value)
  }
})

/**
 * 选择某个 trace，并加载审计详情。
 *
 * @param traceId 全链路追踪 ID。
 *
 * 调用链：
 * table row click
 *   → handleTraceRowClick(row)
 *   → selectTrace(row.trace_id)
 *   → audit.loadDetail(traceId)
 *   → audit.verify(traceId)
 */
async function selectTrace(traceId: string) {
  selectedTrace.value = traceId
  await audit.loadDetail(traceId)
  await audit.verify(traceId)
}

/**
 * Element Plus 表格行点击回调。
 *
 * @param row 当前点击的审计 trace 摘要。
 */
function handleTraceRowClick(row: AuditTrace) {
  selectTrace(row.trace_id)
}
</script>

<template>
  <div class="ks-page">
    <PageHeader title="审计日志" subtitle="按 trace_id 回溯完整链路，并校验哈希链防篡改" />

    <div class="audit-grid">
      <PageSection title="Trace 列表">
        <el-table :data="audit.traces" @row-click="handleTraceRowClick">
          <el-table-column prop="trace_id" label="Trace ID" min-width="180" />
          <el-table-column prop="intent" label="意图" />
          <el-table-column label="风险">
            <template #default="{ row }">
              <RiskTag :level="row.risk_level" />
            </template>
          </el-table-column>
          <el-table-column label="裁决">
            <template #default="{ row }">
              <StatusTag :status="row.decision" />
            </template>
          </el-table-column>
        </el-table>
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
      title="审计 REST 查询接口尚未接入"
      description="当前 /api/audit/* 系列接口待后端实现；Chat 页 SSE 的 audit_appended 实时展示已可用。"
    />

    <PageSection title="审计记录详情">
      <el-table :data="audit.records">
        <el-table-column prop="seq" label="#" width="80" />
        <el-table-column prop="record_type" label="类型" width="180" />
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="内容">
          <template #default="{ row }">
            <pre>{{ prettyJson(row.content) }}</pre>
          </template>
        </el-table-column>
      </el-table>
    </PageSection>
  </div>
</template>

<style scoped>
.audit-grid {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 16px;
}
pre {
  white-space: pre-wrap;
  max-height: 120px;
  overflow: auto;
  color: #bfdbfe;
}
</style>
