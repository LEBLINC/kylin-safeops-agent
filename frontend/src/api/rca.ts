import { request } from './request'
import { isMockEnabled } from './mock-flag'
import { mockGetRcaResult, mockStartRcaAnalysis } from './mock'
import type { RcaApiResponse, RcaProblemType, RcaResult } from '@/types/rca'

/**
 * rca.ts
 *
 * RCA 根因分析接口模块。
 *
 * 使用位置：
 * - RcaView.vue 独立根因分析页面；
 * - ChatView.vue 右侧 RCA 展示使用的是事件流 rca.data.report，不直接调用这里。
 *
 * 与 stream.py 的关系：
 * - stream.py 只规定 rca 事件的 data 形态是 { report: dict }；
 * - report 内部字段没有在 stream.py 强类型定义；
 * - 因此前端在 types/rca.ts 中定义了建议结构 RcaReport / RcaResult；
 * - 后续 mcp_servers/rca/ 和后端 RCAEngine.analyze() 建议按该结构返回。
 *
 * Mock 规则：
 * - VITE_MOCK_ENABLED=true 时，RcaView 也必须走 api 层；
 * - 页面不再直接写死假 RCA 数据；
 * - mock.ts 会根据 problem_type 返回四类 RCA 演示报告。
 */

/**
 * 发起 RCA 分析。
 *
 * 请求方式：POST /api/rca/analyze
 * 使用位置：RcaView.vue 点击“开始分析”。
 *
 * 请求参数：
 * @param data.problem_type 问题类型，例如 disk_full / zombie_process / io_high / config_drift。
 * @param data.description 用户输入的问题描述。
 *
 * 返回数据：
 * @returns trace_id 本次 RCA 分析的追踪 ID。前端随后调用 getRcaResult(trace_id) 获取报告。
 *
 * 说明：
 * RCA 分析通常会先采集证据，再生成报告，因此真实后端可能是异步过程。
 * 当前前端先按“发起分析 -> 获取结果”的两步接口设计。
 */
export function startRcaAnalysis(data: { problem_type: RcaProblemType; description: string }) {
  if (isMockEnabled()) return mockStartRcaAnalysis(data)
  return request.post<{ trace_id: string }, { trace_id: string }>('/api/rca/analyze', data)
}

/**
 * 获取 RCA 分析结果。
 *
 * 请求方式：GET /api/rca/{trace_id}
 * 使用位置：RcaView.vue 在 startRcaAnalysis() 返回 trace_id 后调用。
 *
 * 返回字段：
 * - trace_id：分析链路 ID；
 * - problem_type：问题类型；
 * - summary：RCA 总结；
 * - root_cause_candidates：根因候选；
 * - evidence_chain：证据链；
 * - safe_actions：安全建议；
 * - dangerous_actions_rejected：被拒绝的危险动作。
 */
export async function getRcaResult(traceId: string) {
  if (isMockEnabled()) return mockGetRcaResult(traceId)
  const resp = await request.get<RcaApiResponse, RcaApiResponse>(`/api/rca/${traceId}`)
  return { trace_id: resp.trace_id, ...resp.report } as RcaResult
}
