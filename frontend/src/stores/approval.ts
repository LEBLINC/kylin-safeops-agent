import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
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
      // H10：状态更新只在后端确认成功后执行。后端失败 → 提示错误 + 保持 pending，
      // 不再无条件标记 approved（旧实现 catch 吞掉异常后仍改状态 = 审批假成功）。
      try {
        await approveAction(id)
      } catch (error) {
        ElMessage.error(`审批通过失败：${(error as Error).message || '后端不可用'}，状态保持待审批`)
        return
      }
      this.pending = this.pending.map(
        item => item.approval_id === id ? { ...item, status: 'approved' as const } : item
      )
    },

    async reject(id: string) {
      // H10：同 approve，状态更新只在后端确认成功后执行。
      try {
        await rejectAction(id)
      } catch (error) {
        ElMessage.error(`审批拒绝失败：${(error as Error).message || '后端不可用'}，状态保持待审批`)
        return
      }
      this.pending = this.pending.map(
        item => item.approval_id === id ? { ...item, status: 'rejected' as const } : item
      )
    }
  }
})
