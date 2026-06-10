import type { RiskLevel } from '@/types/policy'

/**
 * risk.ts
 *
 * 风险等级和安全裁决的展示工具。
 *
 * 这里不做真正的安全判断，真正的 allow/deny/confirm 应由后端策略引擎决定。
 * 前端只把后端返回的风险等级转换成中文标签和颜色。
 */

/**
 * riskMap
 *
 * R0~R4 风险等级的前端展示映射。
 *
 * 字段说明：
 * - label：中文含义；
 * - effect/type：传给 Element Plus el-tag 的样式；
 * - color：页面中需要自定义颜色时使用。
 */
export const riskMap: Record<RiskLevel, { label: string; effect: 'dark' | 'light'; type: 'primary' | 'success' | 'warning' | 'danger' | 'info'; color: string }> = {
  R0: { label: '只读查询', effect: 'dark', type: 'primary', color: '#3b82f6' },
  R1: { label: '轻量诊断', effect: 'dark', type: 'success', color: '#22c55e' },
  R2: { label: '需确认', effect: 'dark', type: 'warning', color: '#f59e0b' },
  R3: { label: '高风险', effect: 'dark', type: 'danger', color: '#fb923c' },
  R4: { label: '禁止执行', effect: 'dark', type: 'danger', color: '#ef4444' }
}

/**
 * 将风险等级转换成中文展示文本。
 *
 * 入参：
 * @param level 风险等级，通常是 R0~R4。
 *
 * 返回：
 * - 例如 "R2 需确认"。
 * - 未知等级返回 "未知"。
 */
export function riskLabel(level?: string) {
  if (!level || !(level in riskMap)) return '未知'
  return `${level} ${riskMap[level as RiskLevel].label}`
}

/**
 * 将安全裁决英文值转换成中文。
 *
 * 入参：
 * @param decision 后端返回的裁决值，例如 allow、deny、confirm。
 *
 * 返回：
 * - 用于 SecurityDecisionCard、PolicyView、AuditView 展示。
 */
export function decisionLabel(decision?: string) {
  const map: Record<string, string> = {
    allow: '允许',
    deny: '拒绝',
    confirm: '需确认'
  }
  return decision ? map[decision] ?? decision : '未知'
}
