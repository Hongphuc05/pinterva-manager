import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AccountantPaymentsPage } from './AccountantPaymentsPage'

const logout = vi.fn()
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'kt1', role: 'accountant', full_name: 'Kế Toán An', username: 'kt' }, logout }),
}))

const api = vi.hoisted(() => ({ apiFetch: vi.fn(), apiFetchBlob: vi.fn() }))
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  apiFetch: api.apiFetch,
  apiFetchBlob: api.apiFetchBlob,
}))

const dan = {
  designer_id: 'dan1', designer_name: 'Dân', username: 'dan', pending_count: 2, pending_amount: 95000, has_qr: true,
}
const tram = {
  designer_id: 'tram1', designer_name: 'Trâm', username: 'tram', pending_count: 1, pending_amount: 40000, has_qr: false,
}
const danDetail = {
  ...dan,
  orders: [
    { order_id: 'o1', external_order_id: 'DJ-1', product_name: 'Áo A', thumbnail_url: null, submitted_at: '2026-09-21T10:00:00Z' },
    { order_id: 'o2', external_order_id: 'DJ-2', product_name: 'Áo B', thumbnail_url: null, submitted_at: '2026-09-22T10:00:00Z' },
  ],
}

function routeFetch(overrides: Record<string, unknown> = {}) {
  api.apiFetch.mockReset().mockImplementation((path: string, init?: RequestInit) => {
    if (path === '/accountant/designers') return Promise.resolve(overrides.designers ?? [dan, tram])
    if (path === '/accountant/designers/dan1') return Promise.resolve(overrides.danDetail ?? danDetail)
    if (path === '/finance/payment-history?page=1&page_size=50') return Promise.resolve(overrides.history ?? { batches: [], total: 0, page: 1, page_size: 50, total_pages: 1 })
    if (path.includes('/bank-qr')) return Promise.resolve({ images: [] })
    if (path.includes('/pay')) {
      if (overrides.payImpl) return (overrides.payImpl as (i?: RequestInit) => Promise<unknown>)(init)
      return Promise.resolve({ ok: true, paid_count: 2, total_amount: 95000 })
    }
    return Promise.reject(new Error(`unexpected path ${path}`))
  })
  api.apiFetchBlob.mockReset().mockResolvedValue(new Blob())
}

beforeEach(() => {
  routeFetch()
  logout.mockReset()
})

describe('AccountantPaymentsPage', () => {
  it('lists designers waiting for payment, amounts only (no per-order rate)', async () => {
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Dân')).toBeInTheDocument())
    expect(screen.getByText('2 đơn chờ thanh toán')).toBeInTheDocument()
    expect(screen.getByText('95.000 đ')).toBeInTheDocument()
    expect(screen.getByText('Trâm')).toBeInTheDocument()
    expect(screen.getByText('Chưa có QR')).toBeInTheDocument() // Trâm only
  })

  it('opens a designer, shows their orders (no rate), pays, and the row is gone afterwards', async () => {
    const user = userEvent.setup()
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Dân')).toBeInTheDocument())

    await user.click(screen.getByText('Dân'))
    const modal = () => within(screen.getByTestId('designer-pay-modal'))
    await waitFor(() => expect(modal().getByText('DJ-1')).toBeInTheDocument())
    expect(modal().getByText('DJ-2')).toBeInTheDocument()
    expect(modal().queryByText(/40\.000|55\.000/)).not.toBeInTheDocument() // no per-order price shown, only the total

    await user.click(modal().getByText('Thanh toán'))
    await waitFor(() => expect(modal().getByText('Quét QR để chuyển khoản')).toBeInTheDocument())

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    // After paying, Dân drops out of the pending list — the next fetch must return only Trâm.
    routeFetch({ designers: [tram] })
    await user.click(modal().getByText('Xác nhận đã thanh toán'))

    expect(confirmSpy).toHaveBeenCalledWith('Bạn chắc chắn đã thanh toán xong rồi chứ?')
    await waitFor(() => expect(screen.queryByTestId('designer-pay-modal')).not.toBeInTheDocument())
    await waitFor(() => expect(screen.queryByText('Dân')).not.toBeInTheDocument())
    expect(screen.getByText('Trâm')).toBeInTheDocument()
    confirmSpy.mockRestore()
  })

  it('does nothing when the confirm warning is declined', async () => {
    const user = userEvent.setup()
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Dân')).toBeInTheDocument())
    await user.click(screen.getByText('Dân'))
    const modal = () => within(screen.getByTestId('designer-pay-modal'))
    await waitFor(() => expect(modal().getByText('DJ-1')).toBeInTheDocument())
    await user.click(modal().getByText('Thanh toán'))
    await waitFor(() => expect(modal().getByText('Quét QR để chuyển khoản')).toBeInTheDocument())

    vi.spyOn(window, 'confirm').mockReturnValue(false)
    await user.click(modal().getByText('Xác nhận đã thanh toán'))
    expect(api.apiFetch).not.toHaveBeenCalledWith(expect.stringContaining('/pay'), expect.anything())
    expect(modal().getByText('Quét QR để chuyển khoản')).toBeInTheDocument() // still open
  })

  it('a designer without a QR can still be paid, with a note instead of an image', async () => {
    const user = userEvent.setup()
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Trâm')).toBeInTheDocument())
    routeFetch({ danDetail: { ...tram, orders: [{ order_id: 'o3', external_order_id: 'DJ-3', product_name: null, thumbnail_url: null, submitted_at: null }] } })
    api.apiFetch.mockImplementation((path: string) => {
      if (path === '/accountant/designers/tram1') return Promise.resolve({ ...tram, orders: [{ order_id: 'o3', external_order_id: 'DJ-3', product_name: null, thumbnail_url: null, submitted_at: null }] })
      if (path.includes('/bank-qr')) return Promise.resolve({ images: [] })
      return Promise.resolve([dan, tram])
    })
    await user.click(screen.getByText('Trâm'))
    const modal = () => within(screen.getByTestId('designer-pay-modal'))
    await waitFor(() => expect(modal().getByText('DJ-3')).toBeInTheDocument())
    await user.click(modal().getByText('Thanh toán'))
    await waitFor(() => expect(modal().getByText('Designer chưa tải ảnh QR ngân hàng.')).toBeInTheDocument())
    expect(modal().getByText('Xác nhận đã thanh toán')).toBeEnabled()
  })

  it('a server conflict (data changed) closes the modal and refreshes instead of pretending success', async () => {
    const user = userEvent.setup()
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Dân')).toBeInTheDocument())
    await user.click(screen.getByText('Dân'))
    const modal = () => within(screen.getByTestId('designer-pay-modal'))
    await waitFor(() => expect(modal().getByText('DJ-1')).toBeInTheDocument())
    await user.click(modal().getByText('Thanh toán'))
    await waitFor(() => expect(modal().getByText('Quét QR để chuyển khoản')).toBeInTheDocument())

    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { ApiError } = await import('../api/client')
    routeFetch({
      payImpl: () => Promise.reject(new ApiError(409, 'Danh sách đơn đã thay đổi. Hãy mở lại.')),
      designers: [dan, tram], // the refetch after the conflict
    })
    await user.click(modal().getByText('Xác nhận đã thanh toán'))

    await waitFor(() => expect(screen.queryByTestId('designer-pay-modal')).not.toBeInTheDocument())
    expect(screen.getByText('Dân')).toBeInTheDocument() // nothing was actually paid
  })

  it('opens the shared payment history modal', async () => {
    const user = userEvent.setup()
    routeFetch({
      history: {
        batches: [{
          id: 'b1', paid_at: '2026-09-20T10:00:00Z', paid_by_name: 'Kế Toán An', paid_by_role: 'accountant',
          designer_id: 'dan1', designer_name: 'Dân', order_count: 2, total_amount: 95000, source: 'payment',
          items: [{ order_id: 'o1', external_order_id: 'DJ-1', product_name: 'Áo A', amount: null }],
        }],
        total: 1, page: 1, page_size: 50, total_pages: 1,
      },
    })
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Dân')).toBeInTheDocument())
    await user.click(screen.getByText('Lịch sử'))
    const modal = () => within(screen.getByTestId('payment-history-modal'))
    await waitFor(() => expect(modal().getByText('Dân')).toBeInTheDocument())
    expect(modal().getByText('95.000 đ')).toBeInTheDocument()
  })
})
