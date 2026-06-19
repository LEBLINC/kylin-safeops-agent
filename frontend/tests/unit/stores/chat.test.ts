import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

describe('chat store fetchWhoami', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetModules()
    vi.stubEnv('VITE_MOCK_ENABLED', 'false')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('成功响应 → currentUser/Role/Roles 被填充', async () => {
    const { request } = await import('@/api/request')
    const spy = vi.spyOn(request, 'get').mockResolvedValue({
      user: 'alice',
      roles: ['operator', 'admin'],
      mode: 'proxy',
    } as never)
    const { useChatStore } = await import('@/stores/chat')
    const store = useChatStore()
    await store.fetchWhoami()
    spy.mockRestore()
    expect(store.currentUser).toBe('alice')
    expect(store.currentUserRoles).toEqual(['operator', 'admin'])
    expect(store.currentUserRole).toBe('admin')
  })

  it('失败响应 → 静默降级 viewer（不抛）', async () => {
    const { request } = await import('@/api/request')
    const spy = vi.spyOn(request, 'get').mockRejectedValue(new Error('whoami 401'))
    const { useChatStore } = await import('@/stores/chat')
    const store = useChatStore()
    await expect(store.fetchWhoami()).resolves.not.toThrow()
    spy.mockRestore()
    expect(store.currentUserRole).toBe('viewer')
  })
})
