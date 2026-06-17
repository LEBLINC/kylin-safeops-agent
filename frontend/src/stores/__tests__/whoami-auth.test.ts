import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

describe('whoami identity transition', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetModules()
  })
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('fetchWhoami exists and is callable without crash', async () => {
    vi.stubEnv('VITE_MOCK_ENABLED', 'false')
    const { useChatStore } = await import('@/stores/chat')
    const store = useChatStore()
    await store.fetchWhoami()
    // After failed whoami call (no real backend), falls back silently
    expect(store.currentUser).toBe('')
    expect(store.currentUserRoles).toEqual([])
  })

  it('fetchWhoami skips in mock mode', async () => {
    vi.stubEnv('VITE_MOCK_ENABLED', 'true')
    const { useChatStore } = await import('@/stores/chat')
    const store = useChatStore()
    await store.fetchWhoami()
    expect(store.currentUser).toBe('')
  })

  it('initial state has empty identity', async () => {
    const { useChatStore } = await import('@/stores/chat')
    const store = useChatStore()
    expect(store.currentUser).toBe('')
    expect(store.currentUserRoles).toEqual([])
  })
})