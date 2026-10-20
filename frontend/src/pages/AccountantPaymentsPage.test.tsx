import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearPaymentCaches } from '../features/payments/api'
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

const summary = {
  credited_count: 10, credited_amount: 400000, unpaid_count: 3, unpaid_amount: 135000, paid_count: 7, paid_amount: 265000,
}

function routeFetch(overrides: Record<string, unknown> = {}) {
  api.apiFetch.mockReset().mockImplementation((path: string, init?: RequestInit) => {
    if (path.startsWith('/accountant/summary')) return Promise.resolve(overrides.summary ?? summary)
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
  clearPaymentCaches() // QR images are cached per designer for the session
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

  it('opens a designer: amount on the left, no order list; pays and the period reads 0', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../api/client')
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Dân')).toBeInTheDocument())

    await user.click(screen.getByText('Dân'))
    const modal = () => within(screen.getByTestId('designer-pay-modal'))
    await waitFor(() => expect(modal().getByTestId('pay-amount')).toHaveTextContent('95.000 đ'))
    expect(modal().getByText('2 đơn')).toBeInTheDocument()
    expect(modal().queryByText('DJ-1')).not.toBeInTheDocument() // no per-order list
    expect(modal().queryByText('Thanh toán')).not.toBeInTheDocument() // no intermediate step either

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    // After paying, Dân drops out of the list and his orders for this period are gone (404).
    routeFetch({ designers: [tram] })
    api.apiFetch.mockImplementation(((path: string, init?: RequestInit) => {
      if (path === '/accountant/designers/dan1') return Promise.reject(new ApiError(404, 'Designer này không còn đơn chờ thanh toán.'))
      if (path === '/accountant/designers') return Promise.resolve([tram])
      if (path.includes('/pay')) {
        expect(JSON.parse(init!.body as string)).toEqual({ order_ids: ['o1', 'o2'], expected_total: 95000 })
        return Promise.resolve({ ok: true, paid_count: 2, total_amount: 95000 })
      }
      return Promise.resolve({ images: [] })
    }) as never)
    await user.click(modal().getByText('Xác nhận đã thanh toán'))

    expect(confirmSpy).toHaveBeenCalledWith('Bạn chắc chắn đã thanh toán xong rồi chứ?')
    await waitFor(() => expect(modal().getByTestId('pay-amount')).toHaveTextContent('0 đ'))
    expect(modal().getByText('Không có đơn chờ thanh toán trong khoảng này.')).toBeInTheDocument()
    expect(modal().getByText('Xác nhận đã thanh toán')).toBeDisabled()
    await waitFor(() => expect(screen.queryByText('Dân', { selector: 'p' })).not.toBeInTheDocument())
    confirmSpy.mockRestore()
  })

  it('does nothing when the confirm warning is declined', async () => {
    const user = userEvent.setup()
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Dân')).toBeInTheDocument())
    await user.click(screen.getByText('Dân'))
    const modal = () => within(screen.getByTestId('designer-pay-modal'))
    await waitFor(() => expect(modal().getByTestId('pay-amount')).toHaveTextContent('95.000 đ'))

    vi.spyOn(window, 'confirm').mockReturnValue(false)
    await user.click(modal().getByText('Xác nhận đã thanh toán'))
    expect(api.apiFetch).not.toHaveBeenCalledWith(expect.stringContaining('/pay'), expect.anything())
    expect(modal().getByTestId('pay-amount')).toHaveTextContent('95.000 đ') // still open and unchanged
  })

  it('a designer without a QR can still be paid, with a note instead of an image', async () => {
    const user = userEvent.setup()
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Trâm')).toBeInTheDocument())
    api.apiFetch.mockImplementation((path: string) => {
      if (path === '/accountant/designers/tram1') return Promise.resolve({ ...tram, orders: [{ order_id: 'o3', external_order_id: 'DJ-3', product_name: null, thumbnail_url: null, submitted_at: null }] })
      if (path.includes('/bank-qr')) return Promise.resolve({ images: [] })
      return Promise.resolve([dan, tram])
    })
    await user.click(screen.getByText('Trâm'))
    const modal = () => within(screen.getByTestId('designer-pay-modal'))
    await waitFor(() => expect(modal().getByTestId('pay-amount')).toHaveTextContent('40.000 đ'))
    await waitFor(() => expect(modal().getByText('Designer chưa tải ảnh QR ngân hàng.')).toBeInTheDocument())
    expect(modal().getByText('Xác nhận đã thanh toán')).toBeEnabled()
  })

  it('shows the QR image next to the amount', async () => {
    const user = userEvent.setup()
    routeFetch()
    api.apiFetch.mockImplementation((path: string) => {
      if (path === '/accountant/designers') return Promise.resolve([dan, tram])
      if (path === '/accountant/designers/dan1') return Promise.resolve(danDetail)
      if (path.includes('/bank-qr')) return Promise.resolve({ images: [{ url: '/qr/1' }] })
      return Promise.reject(new Error(`unexpected path ${path}`))
    })
    api.apiFetchBlob.mockResolvedValue(new Blob(['x']))
    URL.createObjectURL = vi.fn(() => 'blob:qr-1')
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Dân')).toBeInTheDocument())
    await user.click(screen.getByText('Dân'))
    const modal = within(await screen.findByTestId('designer-pay-modal'))
    expect(await modal.findByAltText('QR 1 của Dân')).toBeInTheDocument()
  })

  it('a server conflict (data changed) closes the modal and refreshes instead of pretending success', async () => {
    const user = userEvent.setup()
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Dân')).toBeInTheDocument())
    await user.click(screen.getByText('Dân'))
    const modal = () => within(screen.getByTestId('designer-pay-modal'))
    await waitFor(() => expect(modal().getByTestId('pay-amount')).toHaveTextContent('95.000 đ'))

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

  it('shows the credited / unpaid / paid cards for the chosen period', async () => {
    api.apiFetch.mockImplementation((path: string) => {
      if (path === '/accountant/summary') return Promise.resolve(summary)
      if (path.startsWith('/accountant/summary?week=')) {
        return Promise.resolve({ ...summary, credited_count: 2, credited_amount: 80000, unpaid_count: 0, unpaid_amount: 0, paid_count: 2, paid_amount: 80000 })
      }
      if (path.startsWith('/accountant/designers')) return Promise.resolve([dan, tram])
      return Promise.reject(new Error(`unexpected path ${path}`))
    })
    render(<AccountantPaymentsPage />)
    const cards = within(await screen.findByTestId('payment-summary'))
    await waitFor(() => expect(cards.getByText('(135.000 đ)')).toBeInTheDocument())
    expect(cards.getByText('Tổng đơn tính công')).toBeInTheDocument()
    expect(cards.getByText('(400.000 đ)')).toBeInTheDocument()
    expect(cards.getByText('(265.000 đ)')).toBeInTheDocument()

    const select = screen.getByLabelText('Lọc theo thời gian nộp bài') as HTMLSelectElement
    await userEvent.setup().selectOptions(select, select.options[1].value)
    await waitFor(() => expect(cards.getByText('(0 đ)')).toBeInTheDocument()) // unpaid in that week
    expect(cards.getByText('(80.000 đ)', { selector: 'span.text-slate-500' })).toBeInTheDocument()
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

  it('filters by week: the list and the pay popup show only that week\'s orders', async () => {
    const user = userEvent.setup()
    const weekly = { ...dan, pending_count: 1, pending_amount: 40000 }
    api.apiFetch.mockImplementation((path: string) => {
      if (path === '/accountant/designers') return Promise.resolve([dan, tram])
      if (path.startsWith('/accountant/designers?week=')) return Promise.resolve([weekly])
      if (path.startsWith('/accountant/designers/dan1?week=')) return Promise.resolve({ ...weekly, orders: [danDetail.orders[0]] })
      return Promise.reject(new Error(`unexpected path ${path}`))
    })
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Trâm')).toBeInTheDocument())

    const select = screen.getByLabelText('Lọc theo thời gian nộp bài') as HTMLSelectElement
    const thisWeek = select.options[1].value
    expect(select.options[1].textContent).toMatch(/^Tuần này \(\d\d\/\d\d – \d\d\/\d\d\)$/)
    await user.selectOptions(select, thisWeek)
    await waitFor(() => expect(screen.queryByText('Trâm')).not.toBeInTheDocument())
    expect(api.apiFetch).toHaveBeenCalledWith(`/accountant/designers?week=${thisWeek}`)

    await user.click(screen.getByText('Dân'))
    const modal = within(await screen.findByTestId('designer-pay-modal'))
    // The popup starts with the list's week and shows only that week's amount.
    await waitFor(() => expect(modal.getByTestId('pay-amount')).toHaveTextContent('40.000 đ'))
    expect(api.apiFetch).toHaveBeenCalledWith(`/accountant/designers/dan1?week=${thisWeek}`)
  })

  it('the popup has its own period filter: the amount follows it', async () => {
    const user = userEvent.setup()
    api.apiFetch.mockImplementation((path: string) => {
      if (path === '/accountant/designers') return Promise.resolve([dan, tram])
      if (path === '/accountant/designers/dan1') return Promise.resolve(danDetail)
      if (path.startsWith('/accountant/designers/dan1?date_from=2026-10-01&date_to=2026-10-07')) {
        return Promise.resolve({ ...dan, pending_count: 1, pending_amount: 30000, orders: [danDetail.orders[0]] })
      }
      if (path.includes('/bank-qr')) return Promise.resolve({ images: [] })
      return Promise.reject(new Error(`unexpected path ${path}`))
    })
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Dân')).toBeInTheDocument())
    await user.click(screen.getByText('Dân'))
    const modal = within(await screen.findByTestId('designer-pay-modal'))
    await waitFor(() => expect(modal.getByTestId('pay-amount')).toHaveTextContent('95.000 đ'))

    fireEvent.change(modal.getByLabelText('Từ ngày'), { target: { value: '2026-10-01' } })
    fireEvent.change(modal.getByLabelText('Đến ngày'), { target: { value: '2026-10-07' } })
    await waitFor(() => expect(modal.getByTestId('pay-amount')).toHaveTextContent('30.000 đ'))
    expect(modal.getByText('1 đơn')).toBeInTheDocument()
  })

  it('filters by a date range from day to day, both ends included', async () => {
    api.apiFetch.mockImplementation((path: string) => {
      if (path === '/accountant/designers') return Promise.resolve([dan, tram])
      if (path.startsWith('/accountant/designers?date_from=')) return Promise.resolve([tram])
      if (path.startsWith('/accountant/designers?')) return Promise.resolve([dan, tram])
      return Promise.reject(new Error(`unexpected path ${path}`))
    })
    render(<AccountantPaymentsPage />)
    await waitFor(() => expect(screen.getByText('Dân')).toBeInTheDocument())

    const from = screen.getByLabelText('Từ ngày')
    const to = screen.getByLabelText('Đến ngày')
    fireEvent.change(to, { target: { value: '2026-10-10' } })
    fireEvent.change(from, { target: { value: '2026-10-14' } })
    expect(await screen.findByText('Ngày bắt đầu phải trước ngày kết thúc.')).toBeInTheDocument()
    expect(api.apiFetch).not.toHaveBeenCalledWith(expect.stringContaining('date_from=2026-10-14&date_to=2026-10-10'))

    fireEvent.change(to, { target: { value: '2026-10-16' } })
    await waitFor(() => expect(screen.queryByText('Dân')).not.toBeInTheDocument())
    expect(api.apiFetch).toHaveBeenCalledWith('/accountant/designers?date_from=2026-10-14&date_to=2026-10-16')

    fireEvent.click(screen.getByRole('button', { name: 'Xoá ngày' }))
    expect(await screen.findByText('Dân')).toBeInTheDocument()
  })
})
