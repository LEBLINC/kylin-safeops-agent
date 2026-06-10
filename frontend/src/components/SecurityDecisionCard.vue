<script setup lang="ts">
/**
 * SecurityDecisionCard.vue
 *
 * 安全裁决卡片。
 *
 * 使用位置：ChatView.vue 右侧。
 * 数据来源：policy_verdict 事件中的 data.verdict 和 data.per_tool。
 *
 * 组件职责：
 * - 展示整批最终裁决：allow / deny / confirm；
 * - 展示最终风险等级 R0~R4；
 * - 展示命中规则、裁决原因、安全替代方案；
 * - 展示逐工具裁决 per_tool。
 *
 * 注意：
 * 审批按钮不放在这个组件里。审批操作必须在中间聊天区的 ApprovalCard 中完成。
 */
import type { PerToolVerdict, PolicyEvent, PolicyVerdict } from '@/types/policy'
import { computed } from 'vue'
import RiskTag from './RiskTag.vue'
import StatusTag from './StatusTag.vue'

const props = defineProps<{
  event?: PolicyEvent
  verdict?: PolicyVerdict
  perTool?: PerToolVerdict[]
}>()

const data = computed(() => props.event || props.verdict)
const riskLevel = computed(() => data.value?.final_risk)
const rules = computed(() => {
  const matched = data.value?.matched_rules || []
  if (matched.length) return matched.join('、')
  return '-' 
})
</script>

<template>
  <div class="decision ks-card">
    <div class="head">
      <div>
        <strong>安全裁决</strong>
        <p>{{ data?.reason || '暂无安全裁决数据' }}</p>
      </div>
      <StatusTag :status="data?.decision" />
    </div>

    <div class="fields">
      <span>最终风险</span>
      <RiskTag :level="riskLevel" />

      <span>命中规则</span>
      <code>{{ rules }}</code>

      <span>审批要求</span>
      <p>{{ data?.approval_required ? `需要 ${data.required_role || '管理员'} 确认` : '无需审批' }}</p>

      <span>安全替代方案</span>
      <p>{{ data?.safer_alternative || '无' }}</p>
    </div>

    <div v-if="perTool?.length" class="per-tool">
      <strong>逐工具裁决</strong>
      <div v-for="item in perTool" :key="item.tool" class="tool-row">
        <code>{{ item.tool }}</code>
        <StatusTag :status="item.verdict.decision" />
        <RiskTag :level="item.verdict.final_risk" />
        <span>{{ item.verdict.reason || '-' }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.decision {
  padding: 16px;
}
.head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.head strong {
  font-size: 16px;
}
.head p,
.fields p {
  color: var(--ks-text-muted);
  margin: 6px 0 0;
}
.fields {
  margin-top: 14px;
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 10px 12px;
  font-size: 13px;
}
.fields > span {
  color: var(--ks-text-muted);
}
code {
  color: #93c5fd;
}
.per-tool {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--ks-border);
  display: grid;
  gap: 10px;
}
.per-tool > strong {
  font-size: 14px;
}
.tool-row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) auto auto minmax(0, 2fr);
  gap: 8px;
  align-items: center;
  padding: 10px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.58);
  border: 1px solid rgba(51, 65, 85, 0.8);
  font-size: 12px;
}
.tool-row span:last-child {
  color: var(--ks-text-muted);
  line-height: 1.5;
}
</style>
