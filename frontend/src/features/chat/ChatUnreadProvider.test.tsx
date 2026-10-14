import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatBadge, ChatUnreadProvider } from './ChatUnreadProvider'

const auth = vi.hoisted(() => ({ user: { id: 'u1', role: 'admin' } as null | { id: string; role: string } }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: auth.user }) }))
const toast = vi.hoisted(() => ({ showToast: vi.fn() }))
vi.mock('../../context/ToastContext', () => ({ useToast: () => toast }))
const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('../../api/client', () => ({ apiFetch: api.apiFetch }))

const item = (latest: number, count = 1) => ({
  order_id: 'o1', order_code: 'DJ4100001', count, latest_id: latest, sender_name: 'QC Người', snippet: 'Bổ sung file JG nha',
})

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  toast.showToast.mockReset()
  auth.user = { id: 'u1', role: 'admin' }
})
afterEach(() => vi.useRealTimers())

describe('chat unread', () => {
  it('summarises on the first poll, then toasts only each new message once', async () => {
    api.apiFetch.mockReset()
      .mockResolvedValueOnce({ items: [item(10)] })
      .mockResolvedValueOnce({ items: [item(10)] })
      .mockResolvedValueOnce({ items: [item(11, 2)] })
      .mockResolvedValue({ items: [item(11, 2)] })
    render(
      <ChatUnreadProvider>
        <ChatBadge orderId="o1" />
      </ChatUnreadProvider>,
    )
    await waitFor(() => expect(toast.showToast).toHaveBeenCalledWith('1 đơn có tin chat mới từ Printerval.', 'info', 8000))
    expect(await screen.findByText('1 tin chat')).toBeInTheDocument()

    await vi.advanceTimersByTimeAsync(30_000) // same message again: silent
    expect(toast.showToast).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(30_000) // a newer message: one toast naming the order
    await waitFor(() => expect(toast.showToast).toHaveBeenCalledTimes(2))
    expect(toast.showToast).toHaveBeenLastCalledWith('Đơn DJ4100001 có tin nhắn mới trên Tacahu.', 'info', 8000)

    await vi.advanceTimersByTimeAsync(30_000)
    expect(toast.showToast).toHaveBeenCalledTimes(2)
  })

  it('does nothing for roles that cannot read chat (designers included)', async () => {
    auth.user = { id: 's1', role: 'designer' }
    api.apiFetch.mockReset()
    render(<ChatUnreadProvider><span>x</span></ChatUnreadProvider>)
    await vi.advanceTimersByTimeAsync(31_000)
    expect(api.apiFetch).not.toHaveBeenCalled()
  })
})
