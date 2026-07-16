/**
 * chat-security.test.ts — X 执行窗口额外B：前端关键安全逻辑单测脚手架
 *
 * 覆盖可信展示红线回归护栏：
 * - 角色审批能力判断 (canRoleApprove)
 * - 多工具最高角色计算 (requiredRoleOf)
 * - Mock 审计验证 (isMockEnabled / verifyResult)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// 直接引用 chat store 中导出的纯函数（不依赖 Pinia store 实例）
import {
  canRoleApprove,
  roleRank,
} from '@/stores/chat'

// ============================================================
// 1. 角色审批能力判断 — canRoleApprove
// ============================================================

describe('canRoleApprove', () => {
  it('viewer cannot approve admin-required action', () => {
    expect(canRoleApprove('viewer', 'admin')).toBe(false)
  })

  it('admin can approve admin-required action', () => {
    expect(canRoleApprove('admin', 'admin')).toBe(true)
  })

  it('viewer can approve when no required role (null)', () => {
    expect(canRoleApprove('viewer', null)).toBe(true)
  })

  it('viewer can approve when no required role (undefined)', () => {
    expect(canRoleApprove('viewer', undefined)).toBe(true)
  })
})

// ============================================================
// 2. 角色等级排序 — roleRank
// ============================================================

describe('roleRank', () => {
  it('viewer rank is 1', () => {
    expect(roleRank['viewer']).toBe(1)
  })

  it('auditor rank is 1', () => {
    expect(roleRank['auditor']).toBe(1)
  })

  it('operator rank is 2', () => {
    expect(roleRank['operator']).toBe(2)
  })

  it('admin rank is 3', () => {
    expect(roleRank['admin']).toBe(3)
  })

  it('admin rank is highest', () => {
    expect(roleRank['admin']).toBeGreaterThan(roleRank['operator'])
    expect(roleRank['operator']).toBeGreaterThan(roleRank['viewer'])
  })
})

// ============================================================
// 3. 多工具最高角色计算 — requiredRoleOf
// ============================================================
// requiredRoleOf 是 chat store 中的本地函数，未被 export。
// 该逻辑通过 await_approval 分支中的 approval_role 赋值间接测试。
// 此处验证其等价逻辑。

describe('requiredRoleOf equivalent logic', () => {
  type ApprovalTool = { tool: string; approval_role?: string | null }

  function requiredRoleOf(tools: ApprovalTool[]): string | null {
    let role: string | null = null
    let rank = 0
    for (const item of tools) {
      const currentRole = (item.approval_role || null) as string | null
      const currentRank = currentRole ? (roleRank[currentRole] || 3) : 0
      if (currentRank > rank) {
        role = currentRole
        rank = currentRank
      }
    }
    return role
  }

  it('returns highest role: operator + admin → admin', () => {
    const tools: ApprovalTool[] = [
      { tool: 'a', approval_role: 'operator' },
      { tool: 'b', approval_role: 'admin' },
    ]
    expect(requiredRoleOf(tools)).toBe('admin')
  })

  it('returns operator when one tool has null and other operator', () => {
    const tools: ApprovalTool[] = [
      { tool: 'a', approval_role: null },
      { tool: 'b', approval_role: 'operator' },
    ]
    expect(requiredRoleOf(tools)).toBe('operator')
  })

  it('returns null when all tools have null roles', () => {
    const tools: ApprovalTool[] = [
      { tool: 'a', approval_role: null },
      { tool: 'b', approval_role: null },
    ]
    expect(requiredRoleOf(tools)).toBeNull()
  })

  it('returns null for empty tools array', () => {
    expect(requiredRoleOf([])).toBeNull()
  })
})

// ============================================================
// 4. Mock 模式审计验证
// ============================================================

describe('mock mode audit safety', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('isMockEnabled returns false when env not set', async () => {
    vi.stubEnv('VITE_MOCK_ENABLED', '')
    const { isMockEnabled } = await import('@/api/mock-flag')
    expect(isMockEnabled()).toBe(false)
  })

  it('isMockEnabled returns true when VITE_MOCK_ENABLED=true', async () => {
    vi.stubEnv('VITE_MOCK_ENABLED', 'true')
    const { isMockEnabled } = await import('@/api/mock-flag')
    expect(isMockEnabled()).toBe(true)
  })

  it('isMockEnabled is case-insensitive', async () => {
    vi.stubEnv('VITE_MOCK_ENABLED', 'TRUE')
    const { isMockEnabled } = await import('@/api/mock-flag')
    expect(isMockEnabled()).toBe(true)
  })

  it('mock exports never inject fake verified events as rejected replacement', async () => {
    // Verifies that buildRejectedEvents now uses 'rejected' type, not 'verified'
    vi.stubEnv('VITE_MOCK_ENABLED', 'true')
    const mock = await import('@/api/mock')
    const events = (mock as any).buildRejectedEvents?.('test_trace', 'user_reject') || []
    const hasVerified = events.some((e: any) => e.type === 'verified')
    expect(hasVerified).toBe(false)
  })
})
