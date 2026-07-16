/**
 * approval-h10.test.ts — H10 审批假成功修复守门测试
 *
 * 缺口（修复前）：approve()/reject() 的 this.pending.map(...) 状态更新在 try/catch
 * 之外，后端 API 失败被 catch 吞掉后仍把 status 改成 approved/rejected → 审批假成功。
 *
 * 修复：状态更新移进 try（await 成功之后）；catch 改为 ElMessage.error + return，
 * 保持 pending 状态不变。本测试锁死：后端失败 → 状态仍 pending + 弹错误提示。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { ApprovalItem } from '@/types/approval'

// ElMessage.error 断言：hoisted mock 拦截 element-plus
const { errorSpy } = vi.hoisted(() => ({ errorSpy: vi.fn() }))
vi.mock('element-plus', () => ({
  ElMessage: { error: errorSpy, success: vi.fn() },
}))

function makePending(): ApprovalItem {
  return {
    trace_id: 'tr_001',
    user_intent: '压缩轮转 /var/log/app.log',
    risk_level: 'R2',
    state: 'WAIT_APPROVAL',
    approval_role: 'admin',
    created_at: new Date().toISOString(),
  } as ApprovalItem
}

describe('H10 审批假成功修复', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    errorSpy.mockClear()
  })

  afterEach(() => {
    vi.resetModules()
  })

  it('approve 后端失败 → 状态仍 WAIT_APPROVAL + 弹错误提示（不假成功）', async () => {
    const api = await import('@/api/approval')
    const spy = vi.spyOn(api, 'approveAction').mockRejectedValue(new Error('500 后端不可用'))
    const { useApprovalStore } = await import('@/stores/approval')
    const store = useApprovalStore()
    store.pending = [makePending()]

    await store.approve('tr_001')

    expect(store.pending[0].state).toBe('WAIT_APPROVAL')
    expect(errorSpy).toHaveBeenCalledOnce()
    spy.mockRestore()
  })

  it('reject 后端失败 → 状态仍 WAIT_APPROVAL + 弹错误提示（不假成功）', async () => {
    const api = await import('@/api/approval')
    const spy = vi.spyOn(api, 'rejectAction').mockRejectedValue(new Error('503 网关超时'))
    const { useApprovalStore } = await import('@/stores/approval')
    const store = useApprovalStore()
    store.pending = [makePending()]

    await store.reject('tr_001')

    expect(store.pending[0].state).toBe('WAIT_APPROVAL')
    expect(errorSpy).toHaveBeenCalledOnce()
    spy.mockRestore()
  })

  it('approve 后端成功 → 从待审批列表移除（正常路径不误伤）', async () => {
    const api = await import('@/api/approval')
    const spy = vi.spyOn(api, 'approveAction').mockResolvedValue(undefined as never)
    const { useApprovalStore } = await import('@/stores/approval')
    const store = useApprovalStore()
    store.pending = [makePending()]

    await store.approve('tr_001')

    expect(store.pending).toHaveLength(0)
    expect(errorSpy).not.toHaveBeenCalled()
    spy.mockRestore()
  })

  it('reject 后端成功 → 从待审批列表移除（正常路径不误伤）', async () => {
    const api = await import('@/api/approval')
    const spy = vi.spyOn(api, 'rejectAction').mockResolvedValue(undefined as never)
    const { useApprovalStore } = await import('@/stores/approval')
    const store = useApprovalStore()
    store.pending = [makePending()]

    await store.reject('tr_001')

    expect(store.pending).toHaveLength(0)
    expect(errorSpy).not.toHaveBeenCalled()
    spy.mockRestore()
  })
})
