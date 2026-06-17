<script setup lang="ts">
import type { HashChainVerifyRecord } from '@/types/audit'
import type { AuditAppendedData } from '@/types/chat'
import { computed } from 'vue'

/**
 * HashChainViewer.vue
 *
 * 哈希链完整性展示组件。
 *
 * 使用位置：
 * - ChatView.vue 右侧实时审计链：数据来自 audit_appended 事件；
 * - AuditView.vue 审计详情：数据来自 /api/audit/verify 完整校验接口。
 *
 * 数据来源有两种：
 * 1. nodes：实时事件流数据，只包含 seq/curr_hash；
 * 2. records：后端校验接口数据，包含 seq/prev_hash/curr_hash/valid。
 *
 * 组件职责：
 * - 把实时 audit_appended 节点或完整校验记录统一转换成 normalized；
 * - 展示每个节点的序号、前序 hash、当前 hash、校验状态；
 * - 不负责计算 hash，真实 hash 计算和校验必须由后端审计模块完成。
 */
const props = defineProps<{
  /** 整条哈希链是否校验通过。来自 /api/audit/verify；实时 nodes 模式下可以不传。 */
  valid?: boolean
  /** 完整校验记录。来自 AuditView.vue 的 verifyHashChain() 返回值。 */
  records?: HashChainVerifyRecord[]
  /** 实时审计节点。来自 stream.py 的 audit_appended -> { seq, curr_hash }。 */
  nodes?: AuditAppendedData[]
}>()

/**
 * 统一后的链节点列表。
 *
 * 转换规则：
 * - 如果传入 records，说明这是后端完整校验结果，直接展示；
 * - 如果只传入 nodes，说明这是实时事件流，只能用上一条 curr_hash 推导 prev_hash，valid 默认 true；
 * - 如果都没有，返回空数组，页面显示“等待 audit_appended 事件”。
 */
const normalized = computed(() => {
  if (props.records?.length) return props.records
  return (props.nodes || []).map((node, index) => ({
    seq: node.seq,
    record_type: index === (props.nodes?.length || 0) - 1 ? 'latest_audit' : 'audit_record',
    prev_hash: index === 0 ? 'GENESIS' : props.nodes?.[index - 1]?.curr_hash || '-',
    curr_hash: node.curr_hash,
    valid: true
  }))
})
</script>

<template>
  <div class="hash ks-card">
    <div class="hash-head">
      <strong>哈希链完整性</strong>
      <el-tag :type="valid === false ? 'danger' : 'success'" effect="dark">
        {{ valid === false ? '发现异常' : '链式增长' }}
      </el-tag>
    </div>

    <div class="chain" v-if="normalized.length">
      <div v-for="record in normalized" :key="record.seq" class="node" :class="{ invalid: !record.valid }">
        <div class="seq">#{{ record.seq }}</div>
        <div>
          <strong>{{ record.record_type || 'audit_record' }}</strong>
          <p>prev: {{ record.prev_hash?.slice(0, 16) || '-' }}...</p>
          <p>curr: {{ record.curr_hash?.slice(0, 16) || '-' }}...</p>
        </div>
        <el-tag :type="record.valid ? 'success' : 'danger'" effect="dark">
          {{ record.valid ? 'OK' : '异常' }}
        </el-tag>
      </div>
    </div>
    <div v-else class="empty">等待 audit_appended 事件...</div>
  </div>
</template>

<style scoped>
.hash {
  padding: 16px;
}
.hash-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.chain {
  margin-top: 16px;
  display: grid;
  gap: 10px;
}
.node {
  display: grid;
  grid-template-columns: 54px 1fr auto;
  gap: 12px;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--ks-border);
  border-radius: 12px;
  background: rgba(34, 197, 94, 0.07);
}
.node.invalid {
  background: rgba(239, 68, 68, 0.1);
}
.seq {
  width: 42px;
  height: 42px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: #eef4ff;
  color: var(--ks-primary);
}
p,
.empty {
  margin: 4px 0 0;
  color: var(--ks-text-muted);
  font-size: 12px;
}
.empty {
  margin-top: 14px;
}
</style>
