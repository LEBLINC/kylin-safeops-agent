import { request } from './request'
import type { AuditRecord, AuditTrace, HashChainVerifyResult } from '@/types/audit'

/**
 * audit.ts
 *
 * 审计接口模块。
 *
 * 作用：
 * 1. 查询 trace 级审计列表；
 * 2. 查询单个 trace 的审计记录；
 * 3. 调用哈希链完整性校验接口；
 * 4. 导出审计报告。
 *
 * 与 stream.py 的关系：
 * - stream.py 只规定实时事件 audit_appended -> { seq, curr_hash }；
 * - 审计列表、审计详情、完整哈希链校验都属于 REST 查询接口，不在 stream.py 中强约束。
 */

/**
 * 获取审计 trace 列表。
 *
 * 使用位置：
 * - src/views/AuditView.vue 页面初始化时调用。
 *
 * 请求方式：
 * - GET /api/audit/traces
 *
 * 请求参数：
 * @param params 可选筛选条件，例如 trace_id、用户、风险等级、时间范围、裁决结果。
 *
 * 返回数据：
 * - AuditTrace[]
 * - 每条表示一次完整 Agent 请求的摘要。
 */
export function getAuditTraces(params?: Record<string, unknown>) {
  return request.get<AuditTrace[], AuditTrace[]>('/api/audit/traces', { params })
}

/**
 * 获取某个 trace 的审计记录详情。
 *
 * 使用位置：
 * - AuditView.vue 点击某条审计 trace 后加载右侧详情。
 *
 * 请求方式：
 * - GET /api/audit/traces/{trace_id}
 *
 * 请求参数：
 * @param traceId 全链路追踪 ID。
 *
 * 返回数据：
 * - AuditRecord[]
 * - 包含 user_input、tool_call、policy_event、approval、result 等结构化审计记录。
 */
export function getAuditTraceDetail(traceId: string) {
  return request.get<AuditRecord[], AuditRecord[]>(`/api/audit/traces/${traceId}`)
}

/**
 * 校验某个 trace 的哈希链完整性。
 *
 * 使用位置：
 * - AuditView.vue 中点击“校验哈希链”；
 * - HashChainViewer.vue 使用返回结果进行链式展示。
 *
 * 请求方式：
 * - POST /api/audit/verify
 *
 * 请求体：
 * - trace_id: 要校验的 trace。
 *
 * 返回数据：
 * - HashChainVerifyResult
 * - 包含整体 valid、每条记录 seq/curr_hash/prev_hash/valid。
 */
export function verifyHashChain(traceId: string) {
  return request.post<HashChainVerifyResult, HashChainVerifyResult>('/api/audit/verify', {
    trace_id: traceId
  })
}

/**
 * 导出某个 trace 的审计报告。
 *
 * 使用位置：
 * - 后续审计报告导出按钮。
 *
 * 请求方式：
 * - GET /api/audit/traces/{trace_id}/export
 *
 * 返回数据：
 * - Blob 文件流，通常是 PDF/Markdown/JSON 报告。
 */
export function exportAuditReport(traceId: string) {
  return request.get(`/api/audit/traces/${traceId}/export`, { responseType: 'blob' })
}
