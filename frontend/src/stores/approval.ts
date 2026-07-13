import { defineStore } from 'pinia'
import { approveAction, getPendingApprovals, rejectAction } from '@/api/approval'
import { isMockEnabled } from '@/api/mock'
import type { ApprovalItem } from '@/types/approval'

export const useApprovalStore = defineStore('approval', {
  state: () => ({
    pending: [] as ApprovalItem[],
    loading: false,
    loaded: false
  }),

  actions: {
    async load() {
      // 防止并发重复请求
      if (this.loading) return
      this.loading = true
      try {
        this.pending = await getPendingApprovals()
        this.loaded = true
      } catch {
        this.pending = []
        this.loaded = false
        if (isMockEnabled()) {
          this.pending = [
            {
              approval_id: 'mock_ap_001',
              trace_id: 'mock_trace',
              title: '压缩并轮转 /var/log/app.log',
              tool: 'log.compress_rotate',
              risk_level: 'R2',
              status: 'pending',
              reason: '涉及日志文件变更，需要管理员确认',
              approval_role: 'admin',
              args: { path: '/var/log/app.log' },
              dry_run: { passed: true, impact: '会生成 .gz 归档文件，不直接删除原始日志' }
            }
          ]
        }
      } finally {
        this.loading = false
      }
    },

    async approve(id: string) {
      try {
        await approveAction(id)
      } catch {
        // 后端不可用时仍更新本地状态，保证页面不卡死
      }
      this.pending = this.pending.map(
        item => item.approval_id === id ? { ...item, status: 'approved' as const } : item
      )
    },

    async reject(id: string) {
      try {
        await rejectAction(id)
      } catch {
        // 后端不可用时仍更新本地状态
      }
      this.pending = this.pending.map(
        item => item.approval_id === id ? { ...item, status: 'rejected' as const } : item
      )
    }
  }
})
