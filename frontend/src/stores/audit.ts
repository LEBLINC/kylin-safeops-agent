import { defineStore } from 'pinia'
import { getAuditTraceDetail, getAuditTraces, verifyHashChain } from '@/api/audit'
import { isMockEnabled } from '@/api/mock'
import type { AuditRecord, AuditTrace, HashChainVerifyResult } from '@/types/audit'

/**
 * audit.ts Store
 *
 * 审计日志页的全局状态管理。
 *
 * 使用位置：
 * - AuditView.vue。
 *
 * 管理的数据：
 * 1. 审计 trace 列表；
 * 2. 当前选中 trace 的审计记录；
 * 3. 哈希链完整性校验结果；
 * 4. 页面 loading 状态。
 *
 * 与 ChatView 的区别：
 * - ChatView 右侧的哈希链来自实时 audit_appended 事件；
 * - AuditView 的哈希链来自后端审计查询/校验接口，更适合做事后回溯。
 */
export const useAuditStore = defineStore('audit', {
  /**
   * state
   *
   * @field traces 审计 trace 摘要列表。
   * @field records 当前 trace 的审计明细记录。
   * @field verifyResult 当前 trace 的哈希链校验结果。
   * @field loading 审计列表是否正在加载。
   */
  state: () => ({
    traces: [] as AuditTrace[],
    records: [] as AuditRecord[],
    verifyResult: null as HashChainVerifyResult | null,
    loading: false
  }),

  actions: {
    /**
     * 加载审计 trace 列表。
     *
     * 数据流：
     * AuditView.vue onMounted()
     *   → auditStore.loadTraces()
     *   → api/audit.ts getAuditTraces()
     *   → GET /api/audit/traces
     *
     * 失败兜底：
     * - 后端不可用时生成 mock_trace，保证审计页可展示。
     */
    async loadTraces() {
      this.loading = true
      try {
        this.traces = await getAuditTraces()
      } catch {
        if (!isMockEnabled()) return
        this.traces = [
          {
            trace_id: 'mock_trace',
            user: 'operator',
            intent: '磁盘诊断',
            risk_level: 'R2',
            decision: 'confirm',
            created_at: new Date().toISOString(),
            summary: '发现大日志，建议压缩轮转'
          }
        ]
      } finally {
        this.loading = false
      }
    },

    /**
     * 加载某个 trace 的审计明细。
     *
     * 使用位置：
     * - AuditView.vue 点击某条 trace 后调用。
     *
     * 入参：
     * @param traceId 全链路追踪 ID。
     *
     * 后端接口：
     * - GET /api/audit/traces/{trace_id}
     *
     * 返回内容：
     * - AuditRecord[]，每条包含 seq、record_type、content、prev_hash、curr_hash。
     */
    async loadDetail(traceId: string) {
      try {
        this.records = await getAuditTraceDetail(traceId)
      } catch {
        if (!isMockEnabled()) return
        this.records = [
          {
            id: 'r1',
            trace_id: traceId,
            seq: 1,
            record_type: 'user_input',
            content: { message: '帮我看看磁盘为什么快满了' },
            prev_hash: '000000',
            curr_hash: 'a1b2c3',
            created_at: new Date().toISOString()
          },
          {
            id: 'r2',
            trace_id: traceId,
            seq: 2,
            record_type: 'policy_event',
            content: { decision: 'confirm', rule_id: 'LOG001' },
            prev_hash: 'a1b2c3',
            curr_hash: 'd4e5f6',
            created_at: new Date().toISOString()
          }
        ]
      }
    },

    /**
     * 校验某个 trace 的哈希链。
     *
     * 使用位置：
     * - AuditView.vue 点击“校验哈希链”。
     *
     * 入参：
     * @param traceId 全链路追踪 ID。
     *
     * 后端接口：
     * - POST /api/audit/verify
     *
     * 失败兜底：
     * - 如果后端不可用，则根据当前 records 生成全部 valid=true 的演示结果。
     */
    async verify(traceId: string) {
      try {
        this.verifyResult = await verifyHashChain(traceId)
      } catch {
        if (!isMockEnabled()) { this.verifyResult = null; return }
        this.verifyResult = { trace_id: traceId, valid: false, records: [] }
      }
    }
  }
})
