import { defineStore } from 'pinia'
import { getAuditTraceDetail, getAuditTraces, verifyHashChain } from '@/api/audit'
import { isMockEnabled } from '@/api/mock-flag'
import type { AuditRecord, AuditTrace, HashChainVerifyResult } from '@/types/audit'

export const useAuditStore = defineStore('audit', {
  state: () => ({
    traces: [] as AuditTrace[],
    records: [] as AuditRecord[],
    verifyResult: null as HashChainVerifyResult | null,
    loading: false,
    total: 0,
    page: 1,
    pageSize: 15
  }),

  actions: {
    async loadTraces(page?: number) {
      this.loading = true
      if (page !== undefined) this.page = page
      const offset = (this.page - 1) * this.pageSize
      try {
        const resp: any = await getAuditTraces({ limit: this.pageSize, offset })
        const list = resp?.items ?? resp
        this.traces = Array.isArray(list) ? list : []
        this.total = resp?.total ?? this.traces.length
      } catch {
        if (!isMockEnabled()) return
        this.traces = [
          {
            trace_id: 'mock_trace',
            first_user_intent: '磁盘诊断',
            record_count: 5,
            state: 'FINISHED',
            first_seen: new Date().toISOString(),
            last_seen: new Date().toISOString()
          }
        ]
      } finally {
        this.loading = false
      }
    },

    async loadDetail(traceId: string) {
      try {
        const detail: any = await getAuditTraceDetail(traceId)
        this.records = Array.isArray(detail?.records) ? detail.records : Array.isArray(detail) ? detail : []
      } catch {
        if (!isMockEnabled()) return
        this.records = [
          {
            seq: 1,
            phase: 'user_input',
            payload: { user_intent: '帮我看看磁盘为什么快满了' },
            prev_hash: '000000',
            curr_hash: 'a1b2c3',
            created_at: new Date().toISOString()
          },
          {
            seq: 2,
            phase: 'policy_verdict',
            payload: { decision: 'confirm', rule_id: 'LOG001' },
            prev_hash: 'a1b2c3',
            curr_hash: 'd4e5f6',
            created_at: new Date().toISOString()
          }
        ]
      }
    },

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
