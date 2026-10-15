import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PrintervalAlertToasts } from './PrintervalAlertToasts'

const auth = vi.hoisted(() => ({ user: { id: 'a1', role: 'admin' } as null | { id: string; role: string } }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: auth.user }) }))
const toast = vi.hoisted(() => ({ showToast: vi.fn() }))
vi.mock('../../context/ToastContext', () => ({ useToast: () => toast }))
const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('../../api/client', () => ({ apiFetch: api.apiFetch }))

const alert = (n: number) => ({
  id: `x${n}`, created_at: `2026-10-15T05:0${n}:00Z`, order_code: `DJ00${n}`,
  action: 'đổi trạng thái sang Review', error: 'Printerval phản hồi quá chậm',
  manual: `vào Printerval chuyển đơn DJ00${n} sang Review`,
})

beforeEach(() => {
  localStorage.clear()
  toast.showToast.mockReset()
  auth.user = { id: 'a1', role: 'admin' }
  vi.useFakeTimers({ shouldAdvanceTime: true })
})
afterEach(() => vi.useRealTimers())

describe('Printerval write failure toasts', () => {
  it('toasts each failed write with what to do by hand, then only newer ones', async () => {
    api.apiFetch.mockReset()
      .mockResolvedValueOnce({ items: [alert(1)], now: '2026-10-15T05:10:00Z' })
      .mockResolvedValue({ items: [], now: '2026-10-15T05:11:00Z' })
    render(<PrintervalAlertToasts />)

    await waitFor(() => expect(toast.showToast).toHaveBeenCalledTimes(1))
    const [text, kind] = toast.showToast.mock.calls[0]
    expect(kind).toBe('error')
    expect(text).toContain('DJ001')
    expect(text).toContain('Cần làm tay: vào Printerval chuyển đơn DJ001 sang Review')
    expect(api.apiFetch).toHaveBeenCalledWith('/printerval-alerts')

    await vi.advanceTimersByTimeAsync(30_000)
    expect(api.apiFetch).toHaveBeenLastCalledWith(`/printerval-alerts?since=${encodeURIComponent(alert(1).created_at)}`)
    expect(toast.showToast).toHaveBeenCalledTimes(1)
  })

  it('caps a burst and says how many more there are', async () => {
    api.apiFetch.mockReset().mockResolvedValue({ items: [1, 2, 3, 4, 5, 6, 7].map(alert), now: 'n' })
    render(<PrintervalAlertToasts />)
    await waitFor(() => expect(toast.showToast).toHaveBeenCalledTimes(6))
    expect(toast.showToast.mock.calls[5][0]).toContain('Còn 2 lỗi')
  })

  it('does nothing for non-Admin accounts', async () => {
    auth.user = { id: 'd1', role: 'designer' }
    api.apiFetch.mockReset()
    render(<PrintervalAlertToasts />)
    await vi.advanceTimersByTimeAsync(31_000)
    expect(api.apiFetch).not.toHaveBeenCalled()
  })
})
