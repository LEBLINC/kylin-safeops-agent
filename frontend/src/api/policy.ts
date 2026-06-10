import { request } from './request'
import type { PolicyEvent, PolicyRule } from '@/types/policy'

/**
 * policy.ts
 *
 * 安全策略接口模块。
 *
 * 这个文件负责读取“策略规则”和“策略命中事件”。
 * 注意：这里是 REST 查询接口；ChatView.vue 中的实时裁决展示主要来自事件流中的 policy_verdict。
 *
 * 与 stream.py 的关系：
 * - stream.py 已规定 policy_verdict 事件会推送 verdict/per_tool；
 * - 本文件的 /api/policy/rules、/api/policy/events 不在 stream.py 中，需要后端 REST API 单独实现。
 */

/**
 * 查询某次 trace 的策略命中事件。
 *
 * 使用位置：
 * - AuditView.vue 审计详情；
 * - PolicyView.vue 后续可用于查看规则命中历史；
 * - SecurityDecisionCard.vue 一般不直接调用本接口，而是消费事件流 policy_verdict。
 *
 * 请求方式：
 * - GET /api/policy/events?trace_id=xxx
 *
 * 请求参数：
 * @param traceId 可选。传入时只查询某个 trace 的策略事件；不传时可由后端返回最近策略事件。
 *
 * 返回数据：
 * - PolicyEvent[]
 * - 每条包含 rule_id、decision、risk_level、reason、safer_alternative 等字段。
 */
export function getPolicyEvents(traceId?: string) {
  return request.get<PolicyEvent[], PolicyEvent[]>('/api/policy/events', {
    params: { trace_id: traceId }
  })
}

/**
 * 获取策略规则列表。
 *
 * 使用位置：
 * - src/views/PolicyView.vue
 *
 * 请求方式：
 * - GET /api/policy/rules
 *
 * 请求参数：
 * - 无
 *
 * 返回数据：
 * - PolicyRule[]
 * - 用于展示 PI001、CMD001、SVC001、DBLOG001 等规则。
 *
 * 字段说明：
 * - 规则数据不属于 stream.py 事件流字段；
 * - 规则字段来自安全策略引擎，需要和 D/L 后端模块单独对齐。
 */
export function getPolicyRules() {
  return request.get<PolicyRule[], PolicyRule[]>('/api/policy/rules')
}

/**
 * 获取风险等级说明。
 *
 * 使用位置：
 * - PolicyView.vue 可用于展示 R0~R4 的含义；
 * - RiskTag.vue 当前使用前端本地 riskMap，不直接调用该接口。
 *
 * 请求方式：
 * - GET /api/policy/risk-levels
 *
 * 返回数据建议：
 * - R0/R1/R2/R3/R4 对应名称、说明、处置策略、颜色。
 */
export function getRiskLevels() {
  return request.get('/api/policy/risk-levels')
}
