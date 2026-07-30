/**
 * mock-envelope-m8.test.ts — 之七十五 M-8：mock 与真后端返回信封同构
 *
 * 背景（之七十四审批页白屏的根因）：后端 GET /api/approvals 返回信封
 * { items, total }，而前端一度按裸数组消费 → 页面白屏。
 *
 * 修复后 approval.ts 会 `.items` 解包。但只要 mock 仍返回**裸数组**，
 * 这条解包路径在 mock 模式下就永远不被执行——同类信封错配无法在 mock 联调中
 * 暴露，只能等真接后端才炸。mock 与后端信封同构，是让 mock 具备"提前发现
 * 错配"能力的前提，也是本用例存在的意义。
 *
 * M8-1 mock 返回信封形状 { items, total }，不是裸数组
 * M8-2 total 与 items 长度一致（不是写死的假数字）
 * M8-3 items 元素含后端 ApprovalItem 的全部 6 个字段
 * M8-4 getPendingApprovals 在 mock 模式下解包为裸数组（store 契约不变）
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

describe('M-8 mock 信封与后端同构', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('M8-1/M8-2: mock 返回 { items, total } 且 total 与 items 一致', async () => {
    const { mockGetPendingApprovals } = await import('@/api/mock')
    const res = await mockGetPendingApprovals()

    expect(Array.isArray(res)).toBe(false)
    expect(res).toHaveProperty('items')
    expect(res).toHaveProperty('total')
    expect(Array.isArray(res.items)).toBe(true)
    expect(res.total).toBe(res.items.length)
  })

  it('M8-3: items 元素含后端 ApprovalItem 的 6 个字段', async () => {
    const { mockGetPendingApprovals } = await import('@/api/mock')
    const { items } = await mockGetPendingApprovals()

    expect(items.length).toBeGreaterThan(0)
    for (const key of [
      'trace_id',
      'user_intent',
      'risk_level',
      'approval_role',
      'state',
      'created_at'
    ]) {
      expect(items[0]).toHaveProperty(key)
    }
  })

  it('M8-4: mock 模式下 getPendingApprovals 解包为裸数组（store 契约不变）', async () => {
    vi.doMock('@/api/mock-flag', () => ({ isMockEnabled: () => true }))
    const { getPendingApprovals } = await import('@/api/approval')
    const list = await getPendingApprovals()

    expect(Array.isArray(list)).toBe(true)
    expect(list[0]).toHaveProperty('trace_id')
  })
})
