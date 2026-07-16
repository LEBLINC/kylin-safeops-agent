<script setup lang="ts">
import { computed } from 'vue'
import type { ApprovalItem, InlineApproval } from '@/types/approval'
import RiskTag from './RiskTag.vue'
import StatusTag from './StatusTag.vue'
import { formatTime } from '@/utils/time'

/**
 * 审批卡片组件。
 *
 * - inline：对话流 await_approval 事件，事件真实携带 reason/tools；
 * - item：集中审批列表 GET /api/approvals 的真实 DTO，仅展示后端实际返回字段。
 */
const props = defineProps<{
  item?: ApprovalItem
  inline?: InlineApproval
  currentRole?: string
  canApprove?: boolean
}>()

const emit = defineEmits<{
  approve: [id: string]
  reject: [id: string]
  escalate: [id: string]
}>()

const title = computed(() => {
  if (props.inline) return '本批计划需要审批'
  return props.item?.user_intent?.trim() || '未命名审批操作'
})

const roleLabel = computed(() => {
  const role = props.item?.approval_role
  const labels: Record<string, string> = {
    viewer: '只读用户',
    operator: '运维操作员',
    admin: '管理员',
    auditor: '审计员'
  }
  if (!role) return '未声明'
  return labels[role] || role
})
</script>

<template>
  <div class="approval ks-card">
    <template v-if="inline">
      <div class="head">
        <div>
          <strong>{{ title }}</strong>
          <p>{{ inline.reason }}</p>
        </div>
        <StatusTag :status="inline.status" />
      </div>

      <div class="atomic-tip">
        <el-tag type="warning" effect="dark">原子计划</el-tag>
        <span>批准或拒绝会作用于整批工具，不支持逐个工具审批。</span>
      </div>

      <div class="meta inline-meta">
        <span>当前角色</span><code>{{ currentRole || '-' }}</code>
        <span>所需角色</span><code>{{ inline.approval_role || '无' }}</code>
      </div>

      <div class="tool-list">
        <strong>待审批工具</strong>
        <div v-for="tool in inline.tools" :key="tool.tool" class="tool-item">
          <code>{{ tool.tool }}</code>
          <span>所需角色：{{ tool.approval_role || '无' }}</span>
        </div>
      </div>

      <div v-if="inline.status === 'pending'" class="actions">
        <template v-if="canApprove">
          <el-button type="success" @click="emit('approve', inline.trace_id)">批准整批执行</el-button>
          <el-button type="danger" plain @click="emit('reject', inline.trace_id)">拒绝整批执行</el-button>
        </template>
        <template v-else>
          <el-button type="warning" @click="emit('escalate', inline.trace_id)">申请转管理员审批</el-button>
        </template>
      </div>

      <p v-if="inline.status === 'pending' && !canApprove" class="permission-warning">
        当前角色权限不足，不能直接批准该批计划。
      </p>
      <p v-if="inline.status === 'escalated'" class="permission-warning">
        已提交管理员审批，请等待管理员处理。
      </p>
    </template>

    <template v-else-if="item">
      <div class="head centralized-head">
        <div class="title-block">
          <span class="card-kicker">待审批操作</span>
          <strong>{{ title }}</strong>
          <p>该操作已进入人工审批闸，审批结果将作用于对应执行链路。</p>
        </div>
        <StatusTag :status="item.state" />
      </div>

      <div class="detail-grid">
        <div class="detail-item">
          <span>风险等级</span>
          <RiskTag :level="item.risk_level" />
        </div>
        <div class="detail-item">
          <span>审批角色</span>
          <strong>{{ roleLabel }}</strong>
        </div>
        <div class="detail-item">
          <span>进入队列</span>
          <strong>{{ formatTime(item.created_at) }}</strong>
        </div>
      </div>

      <div class="trace-row">
        <span>Trace ID</span>
        <code :title="item.trace_id">{{ item.trace_id }}</code>
      </div>

      <div v-if="item.state === 'WAIT_APPROVAL'" class="actions centralized-actions">
        <el-button type="success" @click="emit('approve', item.trace_id)">通过并继续执行</el-button>
        <el-button type="danger" plain @click="emit('reject', item.trace_id)">拒绝执行</el-button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.approval {
  padding: 18px;
}

.head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.head p {
  margin: 6px 0 0;
  color: var(--ks-text-muted);
  line-height: 1.65;
}

.centralized-head {
  align-items: flex-start;
}

.title-block {
  min-width: 0;
}

.title-block > strong {
  display: block;
  margin-top: 6px;
  font-size: 17px;
  line-height: 1.45;
}

.card-kicker {
  color: var(--ks-primary);
  font-size: 11px;
  font-weight: 800;
}

.atomic-tip {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  align-items: center;
  color: #b45309;
  font-size: 12px;
  line-height: 1.5;
}

.meta {
  margin: 14px 0;
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 10px;
  font-size: 13px;
}

.meta span {
  color: var(--ks-text-muted);
}

.detail-grid {
  margin-top: 18px;
  padding: 14px;
  display: grid;
  grid-template-columns: 1fr 1fr minmax(170px, 1.2fr);
  gap: 14px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.58);
}

.detail-item {
  min-width: 0;
}

.detail-item > span,
.detail-item > strong {
  display: block;
}

.detail-item > span {
  margin-bottom: 7px;
  color: var(--ks-text-muted);
  font-size: 11px;
}

.detail-item > strong {
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-row {
  margin-top: 12px;
  padding: 11px 12px;
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  border-top: 1px solid var(--ks-border);
  border-bottom: 1px solid var(--ks-border);
  color: var(--ks-text-muted);
  font-size: 12px;
}

.trace-row code {
  overflow: hidden;
  color: var(--ks-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-list {
  display: grid;
  gap: 8px;
  margin: 12px 0;
}

.tool-list > strong {
  font-size: 14px;
}

.tool-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 10px;
  border: 1px solid var(--ks-border);
  border-radius: 10px;
  background: #f8fafc;
  font-size: 12px;
}

.tool-item span {
  color: var(--ks-text-muted);
}

.actions {
  margin-top: 14px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.centralized-actions {
  justify-content: flex-end;
}

.permission-warning {
  margin: 10px 0 0;
  color: #b45309;
  font-size: 12px;
}

@media (max-width: 720px) {
  .detail-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .centralized-head {
    flex-direction: column;
  }

  .centralized-actions {
    justify-content: flex-start;
  }
}
</style>

