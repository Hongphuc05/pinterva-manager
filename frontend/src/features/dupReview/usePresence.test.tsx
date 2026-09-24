import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useWorkerPresence } from './usePresence'

const state = vi.hoisted(() => ({ role: 'support' as string | null }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: state.role ? { role: state.role } : null }) }))
const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('../../api/client', () => ({ apiFetch: api.apiFetch }))

beforeEach(() => {
  vi.useFakeTimers()
  api.apiFetch.mockReset().mockResolvedValue({ devices: [] })
})
afterEach(() => vi.useRealTimers())

describe('useWorkerPresence', () => {
  it('beats immediately and then every 20 seconds while the web is open', () => {
    state.role = 'support'
    const { unmount } = renderHook(() => useWorkerPresence())
    expect(api.apiFetch).toHaveBeenCalledTimes(1)
    expect(api.apiFetch).toHaveBeenCalledWith('/support-worker/presence', { method: 'POST' })
    vi.advanceTimersByTime(60_000)
    expect(api.apiFetch).toHaveBeenCalledTimes(4)
    unmount() // closing the page stops the beats: the API pauses the machines soon after
    vi.advanceTimersByTime(60_000)
    expect(api.apiFetch).toHaveBeenCalledTimes(4)
  })

  it('does nothing for a designer or a signed-out visitor', () => {
    for (const role of ['designer', null]) {
      state.role = role
      renderHook(() => useWorkerPresence())
    }
    vi.advanceTimersByTime(60_000)
    expect(api.apiFetch).not.toHaveBeenCalled()
  })

  it('a failing beat does not break the page', async () => {
    state.role = 'admin'
    api.apiFetch.mockRejectedValue(new Error('offline'))
    expect(() => renderHook(() => useWorkerPresence())).not.toThrow()
    await vi.advanceTimersByTimeAsync(20_000)
  })
})
