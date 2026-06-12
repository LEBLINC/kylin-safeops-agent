<script setup lang="ts">
import type { ApprovalItem, InlineApproval } from '@/types/approval'
import { computed } from 'vue'
import RiskTag from './RiskTag.vue'
import StatusTag from './StatusTag.vue'
import { prettyJson } from '@/utils/format'

/**
 * ApprovalCard.vue
 *
 * 审批卡片组件，有两种使用场景：
 * 1. ChatView.vue 中间聊天区：使用 inline 属性，处理当前对话里的多工具原子审批；
 * 2. ApprovalView.vue 集中审批页：使用 item 属性，展示管理员待办审批单。
 *
 * 重要设计：
 * - 对话内审批必须显示在“中间聊天区”，不能放到右侧执行详情里；
 * - await_approval.data.tools 表示一批需要确认的工具；
 * - 用户的批准/拒绝作用于整批原子计划，不支持逐个工具审批；
 * - 当前用户权限不足时，不显示“批准”操作，而是显示“申请转管理员审批”。
 */

const props = defineProps<{
  /** 审批页中的审批单数据，来源 GET /api/approvals?status=pending。 */
  item?: ApprovalItem
  /** 对话内审批数据，来源 await_approval StreamEvent。 */
  inline?: InlineApproval
  /** 当前用户角色，例如 Viewer / Operator / Admin。 */
  currentRole?: string
  /** 当前用户是否满足 inline.approval_role。 */
  canApprove?: boolean
}>()

const emit = defineEmits<{
  /** 批准审批。ChatView 中表示批准整批原子计划，ApprovalView 中表示通过审批单。 */
  approve: [id: string]
  /** 拒绝审批。ChatView 中表示拒绝整批原子计划。 */
  reject: [id: string]
  /** 权限不足时申请转管理员审批。只用于 ChatView 内联审批。 */
  escalate: [id: string]
}>()

const title = computed(() => props.inline ? '本批计划需要审批' : props.item?.title || '审批单')
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

      <div class="meta">
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
        当前角色权限不足，不能直接批准该批计划。你可以提交给管理员在审批页集中处理。
      </p>
      <p v-if="inline.status === 'escalated'" class="permission-warning">
        已提交管理员审批，请等待管理员处理。
      </p>
    </template>

    <template v-else-if="item">
      <div class="head">
        <div>
          <strong>{{ item.title }}</strong>
          <p>{{ item.reason }}</p>
        </div>
        <StatusTag :status="item.status" />
      </div>

      <div class="meta">
        <span>风险等级</span><RiskTag :level="item.risk_level" />
        <span>工具</span><code>{{ item.tool || '-'  }}</code>
        <span>角色要求</span><code>{{ item.approval_role || 'Admin' }}</code>
      </div>

      <el-collapse v-if="item.args || item.dry_run">
        <el-collapse-item title="参数与 dry-run" name="args">
          <pre>{{ prettyJson({ args: item.args, dry_run: item.dry_run }) }}</pre>
        </el-collapse-item>
      </el-collapse>

      <div v-if="item.status === 'pending'" class="actions">
        <el-button type="success" @click="emit('approve', item.approval_id)">通过</el-button>
        <el-button type="danger" plain @click="emit('reject', item.approval_id)">拒绝</el-button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.approval {
  padding: 16px;
}
.head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.head p {
  color: var(--ks-text-muted);
  margin: 6px 0 0;
}
.atomic-tip {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  align-items: center;
  color: #fde68a;
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
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.58);
  border: 1px solid var(--ks-border);
  font-size: 12px;
}
.tool-item span {
  color: var(--ks-text-muted);
}
pre {
  white-space: pre-wrap;
  color: #bfdbfe;
  background: #0b1220;
  border-radius: 10px;
  padding: 12px;
}
.actions {
  margin-top: 14px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.permission-warning {
  margin: 10px 0 0;
  color: #fbbf24;
  font-size: 12px;
}
</style>
