<script setup lang="ts">
import type { RiskLevel } from '@/types/policy'
import { riskMap } from '@/utils/risk'

/**
 * RiskTag.vue
 *
 * 风险等级标签组件。
 *
 * 使用位置：
 * - DashboardView.vue 指标风险提示；
 * - ChatView.vue 会话风险和工具风险；
 * - SecurityDecisionCard.vue 展示 final_risk；
 * - PolicyView.vue 展示策略规则风险等级。
 *
 * 数据来源：
 * - PolicyVerdict.final_risk；
 * - ToolDefinition.risk；
 * - ApprovalItem.risk_level；
 * - 前端 Mock 数据。
 *
 * 安全说明：
 * - 本组件只负责展示颜色和文字；
 * - 不做真正的风险判断，真正风险由后端安全策略引擎计算。
 */
const props = defineProps<{
  /** 风险等级，通常是 R0/R1/R2/R3/R4；如果传入未知值则显示“未知”。 */
  level?: RiskLevel | string
}>()

/**
 * 根据风险等级获取标签样式。
 *
 * 返回：
 * - label：中文说明；
 * - type/effect：Element Plus el-tag 样式。
 */
function info() {
  if (!props.level || !(props.level in riskMap)) {
    return { label: '未知', type: 'info' as const, effect: 'dark' as const }
  }
  return riskMap[props.level as RiskLevel]
}
</script>

<template>
  <el-tag :type="info().type" :effect="info().effect">
    {{ level || '-' }} {{ info().label }}
  </el-tag>
</template>
