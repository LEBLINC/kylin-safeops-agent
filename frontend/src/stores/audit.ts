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
    detailLoading: false,
    verifying: false,
    error: '',
    detailError: '',
    total: 0,
    page: 1,
    pageSize: 15
  }),

  actions: {
    async loadTraces(page?: number) {
      this.loading = true
      this.error = ''
      if (page !== undefined) this.page = page
      const offset = (this.page - 1) * this.pageSize
      try {
        const resp: any = await getAuditTraces({ limit: this.pageSize, offset })
        const list = resp?.items ?? resp
        this.traces = Array.isArray(list) ? list : []
        this.total = resp?.total ?? this.traces.length
      } catch {
        this.error = '审计列表加载失败，请确认后端服务正常后重试'
        if (!isMockEnabled()) return
        this.error = ''
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
      this.detailLoading = true
      this.detailError = ''
      try {
        const detail: any = await getAuditTraceDetail(traceId)
        this.records = Array.isArray(detail?.records) ? detail.records : Array.isArray(detail) ? detail : []
      } catch {
        this.detailError = '审计记录详情加载失败，请重试'
        if (!isMockEnabled()) {
          this.records = []
          return
        }
        this.detailError = ''
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
      } finally {
        this.detailLoading = false
      }
    },

    async verify(traceId: string) {
      this.verifying = true
      try {
        this.verifyResult = await verifyHashChain(traceId)
      } catch {
        if (!isMockEnabled()) {
          this.verifyResult = null
          return
        }
        this.verifyResult = {
          trace_id: traceId,
          valid: false,
          record_count: 0,
          broken_seq: null,
          reason: 'mock 模式无后端校验结果'
        }
      } finally {
        this.verifying = false
      }
    }
  }
})
