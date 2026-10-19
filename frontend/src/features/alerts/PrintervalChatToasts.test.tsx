import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PrintervalChatToasts } from './PrintervalChatToasts'

const auth = vi.hoisted(() => ({ user: { id: 'a1', role: 'admin' } as null | { id: string; role: string } }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: auth.user }) }))
const toast = vi.hoisted(() => ({ showToast: vi.fn() }))
vi.mock('../../context/ToastContext', () => ({ useToast: () => toast }))
const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('../../api/client', () => ({ apiFetch: api.apiFetch }))

const unread = (code: string, count = 1) => ({ order_id: `id-${code}`, order_code: code, count })

beforeEach(() => {
  localStorage.clear()
  toast.showToast.mockReset()
  auth.user = { id: 'a1', role: 'admin' }
  vi.useFakeTimers({ shouldAdvanceTime: true })
})
afterEach(() => vi.useRealTimers())

describe('Printerval chat toasts', () => {
  it('names each order with a new message once, and again only when it gets another one', async () => {
    api.apiFetch.mockReset()
      .mockResolvedValueOnce({ items: [unread('DJ001')], stale: false })
      .mockResolvedValueOnce({ items: [unread('DJ001')], stale: false })
      .mockResolvedValueOnce({ items: [unread('DJ001', 2)], stale: false })
      .mockResolvedValueOnce({ items: [], stale: false })
      .mockResolvedValue({ items: [unread('DJ001')], stale: false })
    render(<PrintervalChatToasts />)

    await waitFor(() => expect(toast.showToast).toHaveBeenCalledTimes(1))
    expect(toast.showToast.mock.calls[0][0]).toContain('DJ001')
    expect(api.apiFetch).toHaveBeenCalledWith('/printerval-chat/unread')

    await vi.advanceTimersByTimeAsync(30_000) // still the same unread message: no new toast
    expect(toast.showToast).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(30_000) // a second message
    expect(toast.showToast).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(30_000) // read on Printerval
    await vi.advanceTimersByTimeAsync(30_000) // then a new message again
    expect(toast.showToast).toHaveBeenCalledTimes(3)
  })

  it('shows nothing when Printerval could not be reached (stale)', async () => {
    api.apiFetch.mockReset().mockResolvedValue({ items: [unread('DJ001')], stale: true })
    render(<PrintervalChatToasts />)
    await vi.advanceTimersByTimeAsync(1_000)
    expect(toast.showToast).not.toHaveBeenCalled()
  })

  it('caps a burst and says how many more there are', async () => {
    api.apiFetch.mockReset().mockResolvedValue({
      items: ['DJ1', 'DJ2', 'DJ3', 'DJ4', 'DJ5', 'DJ6', 'DJ7'].map((code) => unread(code)), stale: false,
    })
    render(<PrintervalChatToasts />)
    await waitFor(() => expect(toast.showToast).toHaveBeenCalledTimes(6))
    expect(toast.showToast.mock.calls[5][0]).toContain('Còn 2 đơn')
  })

  it('does nothing for non-Admin accounts', async () => {
    auth.user = { id: 'd1', role: 'designer' }
    api.apiFetch.mockReset()
    render(<PrintervalChatToasts />)
    await vi.advanceTimersByTimeAsync(31_000)
    expect(api.apiFetch).not.toHaveBeenCalled()
  })
})
