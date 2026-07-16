<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck, Refresh, Warning } from '@element-plus/icons-vue'
import type { AuditAppendedData } from '@/types/chat'

/**
 * 哈希链状态组件。
 *
 * 审计页使用后端 /api/audit/verify 的汇总结果；后端不会返回每个节点的
 * 复算明细，因此这里不再伪造 records。聊天页仍可通过 nodes 展示实时追加节点。
 */
const props = defineProps<{
  valid?: boolean
  recordCount?: number
  brokenSeq?: number | null
  reason?: string
  nodes?: AuditAppendedData[]
  verifying?: boolean
  showVerifyAction?: boolean
}>()

const emit = defineEmits<{
  verify: []
}>()

const hasVerifyResult = computed(() => props.valid !== undefined && props.recordCount !== undefined)
const isRealtime = computed(() => !hasVerifyResult.value && Boolean(props.nodes?.length))

const status = computed(() => {
  if (!hasVerifyResult.value) {
    return isRealtime.value
      ? { label: '实时追加', type: 'info' as const }
      : { label: '尚未校验', type: 'info' as const }
  }
  return props.valid
    ? { label: '校验通过', type: 'success' as const }
    : { label: '发现异常', type: 'danger' as const }
})

const resultTitle = computed(() => {
  if (!hasVerifyResult.value) return '等待服务端校验结果'
  if (props.valid) return '审计记录未发现断链或内容篡改'
  return props.brokenSeq === null || props.brokenSeq === undefined
    ? '审计链校验未通过'
    : `第 ${props.brokenSeq} 条记录开始出现异常`
})

const resultDescription = computed(() => {
  if (!hasVerifyResult.value) {
    return '选择一条 Trace 后，系统会由后端重新计算整条审计链。'
  }
  if (props.valid) {
    return '后端已检查序号连续性、前序哈希引用和当前内容哈希，结果均一致。'
  }
  return props.reason || '服务端复算发现哈希链不连续，请结合审计记录进一步排查。'
})

const realtimeNodes = computed(() => {
  return (props.nodes || []).map((node, index) => ({
    seq: node.seq,
    prevHash: index === 0 ? 'GENESIS' : props.nodes?.[index - 1]?.curr_hash || '-',
    currHash: node.curr_hash
  }))
})
</script>

<template>
  <section class="hash ks-card">
    <header class="hash-head">
      <div>
        <strong>审计链完整性</strong>
        <p>
          这是审计防篡改校验，不是业务执行状态。后端会按顺序重算每条记录的哈希，
          用于发现记录被修改、删除或重排。
        </p>
      </div>

      <div class="hash-actions">
        <el-button
          v-if="showVerifyAction"
          text
          :icon="Refresh"
          :loading="verifying"
          @click="emit('verify')"
        >
          重新校验
        </el-button>
        <el-tag :type="status.type" effect="dark">{{ status.label }}</el-tag>
      </div>
    </header>

    <template v-if="hasVerifyResult">
      <div class="verify-metrics">
        <div>
          <span>参与校验记录</span>
          <strong>{{ recordCount }}</strong>
        </div>
        <div>
          <span>链路状态</span>
          <strong>{{ valid ? '完整' : '异常' }}</strong>
        </div>
        <div>
          <span>首个异常序号</span>
          <strong>{{ brokenSeq === null || brokenSeq === undefined ? '无' : `#${brokenSeq}` }}</strong>
        </div>
      </div>

      <div class="verify-result" :class="{ invalid: valid === false }">
        <el-icon>
          <Warning v-if="valid === false" />
          <CircleCheck v-else />
        </el-icon>
        <div>
          <strong>{{ resultTitle }}</strong>
          <p>{{ resultDescription }}</p>
        </div>
      </div>
    </template>

    <div v-else-if="isRealtime" class="chain">
      <div v-for="node in realtimeNodes" :key="node.seq" class="node">
        <div class="seq">#{{ node.seq }}</div>
        <div>
          <strong>审计记录已追加</strong>
          <p>前序：{{ node.prevHash.slice(0, 16) }}{{ node.prevHash.length > 16 ? '…' : '' }}</p>
          <p>当前：{{ node.currHash.slice(0, 16) }}…</p>
        </div>
        <el-tag type="info" effect="plain">待服务端复算</el-tag>
      </div>
    </div>

    <div v-else class="empty">选择一条 Trace 后自动展示完整性校验结果。</div>
  </section>
</template>

<style scoped>
.hash {
  padding: 20px;
}

.hash-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 22px;
}

.hash-head > div:first-child {
  min-width: 0;
}

.hash-head strong {
  font-size: 16px;
}

.hash-head p {
  max-width: 880px;
  margin: 7px 0 0;
  color: var(--ks-text-muted);
  font-size: 12px;
  line-height: 1.65;
}

.hash-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.verify-metrics {
  margin-top: 18px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.verify-metrics > div {
  padding: 13px 14px;
  border: 1px solid var(--ks-border);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.56);
}

.verify-metrics span,
.verify-metrics strong {
  display: block;
}

.verify-metrics span {
  color: var(--ks-text-muted);
  font-size: 11px;
}

.verify-metrics strong {
  margin-top: 5px;
  font-size: 17px;
}

.verify-result {
  margin-top: 12px;
  padding: 14px;
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  border: 1px solid rgba(22, 163, 74, 0.18);
  border-radius: 13px;
  background: rgba(22, 163, 74, 0.07);
}

.verify-result.invalid {
  border-color: rgba(239, 68, 68, 0.2);
  background: rgba(239, 68, 68, 0.07);
}

.verify-result > .el-icon {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  color: var(--ks-success);
  background: rgba(22, 163, 74, 0.12);
  font-size: 21px;
}

.verify-result.invalid > .el-icon {
  color: var(--ks-danger);
  background: rgba(239, 68, 68, 0.12);
}

.verify-result strong {
  font-size: 13px;
}

.verify-result p {
  margin: 5px 0 0;
  color: var(--ks-text-muted);
  font-size: 12px;
  line-height: 1.55;
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
  background: rgba(37, 99, 235, 0.04);
}

.seq {
  width: 42px;
  height: 42px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  color: var(--ks-primary);
  background: #eef4ff;
}

.node p,
.empty {
  margin: 4px 0 0;
  color: var(--ks-text-muted);
  font-size: 12px;
}

.empty {
  margin-top: 16px;
  padding: 18px;
  border: 1px dashed var(--ks-border);
  border-radius: 12px;
  text-align: center;
}

@media (max-width: 760px) {
  .hash-head {
    flex-direction: column;
  }

  .hash-actions {
    width: 100%;
    justify-content: space-between;
  }

  .verify-metrics {
    grid-template-columns: minmax(0, 1fr);
  }

  .node {
    grid-template-columns: 48px minmax(0, 1fr);
  }

  .node > .el-tag {
    grid-column: 2;
    justify-self: start;
  }
}
</style>
