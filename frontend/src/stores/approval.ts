import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { approveAction, getPendingApprovals, rejectAction } from '@/api/approval'
import { isMockEnabled } from '@/api/mock-flag'
import type { ApprovalItem } from '@/types/approval'

export const useApprovalStore = defineStore('approval', {
  state: () => ({
    pending: [] as ApprovalItem[],
    loading: false,
    loaded: false,
    error: ''
  }),

  actions: {
    async load() {
      if (this.loading) return
      this.loading = true
      this.error = ''
      try {
        this.pending = await getPendingApprovals()
        this.loaded = true
      } catch {
        this.pending = []
        this.loaded = false
        this.error = '接口请求失败，请确认后端审批服务正常后重试'
        if (isMockEnabled()) {
          this.error = ''
          this.pending = [
            {
              trace_id: 'mock_trace',
              user_intent: '压缩并轮转 /var/log/app.log',
              risk_level: 'R2',
              state: 'WAIT_APPROVAL',
              approval_role: 'admin',
              created_at: new Date().toISOString()
            }
          ]
        }
      } finally {
        this.loading = false
      }
    },

    async approve(traceId: string) {
      // H10：状态更新只在后端确认成功后执行。后端失败 → 提示错误 + 保持待审批，
      // 不再无条件视为成功（旧实现 catch 吞掉异常后仍改状态 = 审批假成功）。
      try {
        await approveAction(traceId)
      } catch (error) {
        ElMessage.error(`审批通过失败：${(error as Error).message || '后端不可用'}，状态保持待审批`)
        return
      }
      // 审批通过后该项不再是 WAIT_APPROVAL，从待审批列表移除（工作台只展示待处理项）。
      this.pending = this.pending.filter(item => item.trace_id !== traceId)
      ElMessage.success('已通过，执行链路继续')
    },

    async reject(traceId: string) {
      // H10：同 approve，状态更新只在后端确认成功后执行。
      try {
        await rejectAction(traceId)
      } catch (error) {
        ElMessage.error(`审批拒绝失败：${(error as Error).message || '后端不可用'}，状态保持待审批`)
        return
      }
      // 拒绝后该项不再是 WAIT_APPROVAL，从待审批列表移除。
      this.pending = this.pending.filter(item => item.trace_id !== traceId)
      ElMessage.success('已拒绝该操作')
    }
  }
})
