import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QuickDistributeModal } from './QuickDistributeModal'
import type { OrderSummary, UserOption } from '../pages/OrdersListPage'

describe('QuickDistributeModal', () => {
  const mockDesigners: UserOption[] = [
    { id: 'des-1', username: 'quan_des', full_name: 'Quân Nguyễn', role: 'designer', platform_designer_option: 'quan print' },
    { id: 'des-2', username: 'hoa_des', full_name: 'Hoa Trần', role: 'designer', platform_designer_option: null },
  ]

  const mockWaitingOrders = [
    {
      id: 'o-1',
      external_order_id: 'ORD-1',
      state: 'WAITING',
      work_domain: 'standard',
      product_name: 'Shirt 1',
      duplicate_check_status: 'uncheck',
      created_at: '2026-01-01',
    },
    {
      id: 'o-2',
      external_order_id: 'ORD-2',
      state: 'WAITING',
      work_domain: 'standard',
      product_name: 'Shirt 2',
      duplicate_check_status: 'non_duplicate',
      created_at: '2026-01-01',
    },
    {
      id: 'o-3',
      external_order_id: 'ORD-3',
      state: 'WAITING',
      work_domain: 'standard',
      product_name: 'Shirt 3',
      duplicate_check_status: 'uncheck',
      created_at: '2026-01-01',
    },
    {
      id: 'o-4',
      external_order_id: 'ORD-4',
      state: 'WAITING',
      work_domain: 'standard',
      product_name: 'Shirt 4',
      duplicate_check_status: 'non_duplicate',
      created_at: '2026-01-01',
    },
    {
      id: 'o-5',
      external_order_id: 'ORD-5',
      state: 'WAITING',
      work_domain: 'standard',
      product_name: 'Shirt 5',
      duplicate_check_status: 'non_duplicate',
      created_at: '2026-01-01',
    },
  ] as unknown as OrderSummary[]

  let mockOnClose: () => void
  let mockOnSuccess: () => Promise<void>
  let mockSetFlash: (msg: string) => void

  beforeEach(() => {
    mockOnClose = vi.fn()
    mockOnSuccess = vi.fn().mockResolvedValue(undefined)
    mockSetFlash = vi.fn()
    vi.restoreAllMocks()
  })

  it('renders stats, designer list, and calculates remaining count realtime', () => {
    render(
      <QuickDistributeModal
        isOpen={true}
        onClose={mockOnClose}
        waitingOrders={mockWaitingOrders}
        designers={mockDesigners}
        onSuccess={mockOnSuccess}
        setFlash={mockSetFlash}
      />
    )

    expect(screen.getByText('Chia Đơn Nhanh Cho Designer')).toBeInTheDocument()
    expect(screen.getByText('Tổng Đơn Chờ').parentElement).toHaveTextContent('5')

    // Both designers rendered
    expect(screen.getByText('Quân Nguyễn')).toBeInTheDocument()
    expect(screen.getByText('Hoa Trần')).toBeInTheDocument()

    const inputs = screen.getAllByRole('spinbutton')
    expect(inputs).toHaveLength(2)

    // Type 2 orders for first designer
    fireEvent.change(inputs[0], { target: { value: '2' } })

    // Đã phân bổ = 2, Còn lại = 3
    expect(screen.getByText('Đã Phân Bổ').parentElement).toHaveTextContent('2')
    expect(screen.getByText('Còn Lại').parentElement).toHaveTextContent('3')

    // Type 3 orders for second designer
    fireEvent.change(inputs[1], { target: { value: '3' } })
    expect(screen.getByText('Đã Phân Bổ').parentElement).toHaveTextContent('5')
    expect(screen.getByText('Còn Lại').parentElement).toHaveTextContent('0')
  })

  it('handles Chia đều and Xóa hết buttons', () => {
    render(
      <QuickDistributeModal
        isOpen={true}
        onClose={mockOnClose}
        waitingOrders={mockWaitingOrders}
        designers={mockDesigners}
        onSuccess={mockOnSuccess}
        setFlash={mockSetFlash}
      />
    )

    const distributeEvenlyBtn = screen.getByText('Chia đều')
    fireEvent.click(distributeEvenlyBtn)

    const inputs = screen.getAllByRole('spinbutton') as HTMLInputElement[]
    // 5 orders / 2 designers -> 3 and 2
    expect(inputs[0].value).toBe('3')
    expect(inputs[1].value).toBe('2')
    expect(screen.getByText('Đã Phân Bổ').parentElement).toHaveTextContent('5')

    const clearBtn = screen.getByText('Xóa hết')
    fireEvent.click(clearBtn)

    expect(inputs[0].value).toBe('')
    expect(inputs[1].value).toBe('')
    expect(screen.getByText('Đã Phân Bổ').parentElement).toHaveTextContent('0')
  })

  it('shows warning popup when distributing uncheck orders and executes assignment upon confirmation', async () => {
    const fetchSpy = vi.fn().mockImplementation((url, _init) => {
      if (url === '/api/assignments') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ queued_count: 3 }),
        })
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchSpy)

    render(
      <QuickDistributeModal
        isOpen={true}
        onClose={mockOnClose}
        waitingOrders={mockWaitingOrders}
        designers={mockDesigners}
        onSuccess={mockOnSuccess}
        setFlash={mockSetFlash}
      />
    )

    const inputs = screen.getAllByRole('spinbutton')
    // Distribute 3 orders to Quân (o-1 is uncheck, o-2 is non_duplicate, o-3 is uncheck -> 2 uncheck orders)
    fireEvent.change(inputs[0], { target: { value: '3' } })

    const confirmBtn = screen.getByText(/Xác nhận chia \(3 đơn\)/i)
    fireEvent.click(confirmBtn)

    // Warning modal should pop up
    expect(screen.getByText('Cảnh báo đơn chưa check trùng')).toBeInTheDocument()
    expect(screen.getByText(/2 đơn/)).toBeInTheDocument()

    // Click "Vẫn tiếp tục chia"
    const continueBtn = screen.getByText('Vẫn tiếp tục chia')
    fireEvent.click(continueBtn)

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/assignments',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            order_ids: ['o-1', 'o-2', 'o-3'],
            designer_id: 'des-1',
            printerval_designer: 'quan print',
            printerval_status: 'Doing',
          }),
        })
      )
      expect(mockSetFlash).toHaveBeenCalled()
      expect(mockOnClose).toHaveBeenCalled()
      expect(mockOnSuccess).toHaveBeenCalled()
    })
  })

  it('distributes only the checked (Không trùng lặp) orders when that group is chosen', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ queued_count: 3 }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    render(
      <QuickDistributeModal
        isOpen={true}
        onClose={mockOnClose}
        waitingOrders={mockWaitingOrders}
        initialCheckFilter="checked"
        designers={mockDesigners}
        onSuccess={mockOnSuccess}
        setFlash={mockSetFlash}
      />
    )

    expect(screen.getByRole('radio', { name: /Đã kiểm tra/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText('Tổng Đơn Chờ').parentElement).toHaveTextContent('3') // o-2, o-4, o-5

    fireEvent.change(screen.getAllByRole('spinbutton')[0], { target: { value: '3' } })
    fireEvent.click(screen.getByText(/Xác nhận chia \(3 đơn\)/i))

    expect(screen.queryByText('Cảnh báo đơn chưa check trùng')).not.toBeInTheDocument() // nothing unchecked
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/assignments',
        expect.objectContaining({
          body: JSON.stringify({
            order_ids: ['o-2', 'o-4', 'o-5'],
            designer_id: 'des-1',
            printerval_designer: 'quan print',
            printerval_status: 'Doing',
          }),
        }),
      ),
    )
  })

  it('switches between all, unchecked and checked groups and counts each', () => {
    render(
      <QuickDistributeModal
        isOpen={true}
        onClose={mockOnClose}
        waitingOrders={mockWaitingOrders}
        designers={mockDesigners}
        onSuccess={mockOnSuccess}
        setFlash={mockSetFlash}
      />
    )
    expect(screen.getByText('Tổng Đơn Chờ').parentElement).toHaveTextContent('5')
    fireEvent.click(screen.getByRole('radio', { name: /Chưa kiểm tra \(2\)/ }))
    expect(screen.getByText('Tổng Đơn Chờ').parentElement).toHaveTextContent('2')
    fireEvent.click(screen.getByRole('radio', { name: /Đã kiểm tra/ }))
    expect(screen.getByText('Tổng Đơn Chờ').parentElement).toHaveTextContent('3')
  })

  it('shows each Designer\'s Fix rate under the name and sorts by it', () => {
    const stat = (id: string, rate: number, fixed: number, submitted: number, repeat = 0) => ({
      designer_id: id, submitted_orders: submitted, fixed_orders: fixed, fix_rate: rate, fix_count: fixed,
      max_fixes_per_order: repeat ? 3 : 1, repeat_orders: repeat, distribution: { '1': 0, '2': 0, '3+': repeat },
      excluded: { fake: 0, admin_rejected: 0 },
    })
    const fixStats = new Map([['des-1', stat('des-1', 40, 4, 10, 1)], ['des-2', stat('des-2', 10, 1, 10)]])
    render(
      <QuickDistributeModal isOpen onClose={mockOnClose} waitingOrders={mockWaitingOrders} designers={mockDesigners}
        fixStats={fixStats} fixThreshold={3} onSuccess={mockOnSuccess} setFlash={mockSetFlash} />
    )

    expect(screen.getByText('40%')).toBeInTheDocument()
    expect(screen.getByText('1 đơn Fix ≥3 lần')).toBeInTheDocument()
    const names = () => screen.getAllByText(/Quân Nguyễn|Hoa Trần/).map((el) => el.textContent)
    expect(names()).toEqual(['Quân Nguyễn', 'Hoa Trần'])
    fireEvent.change(screen.getByRole('combobox', { name: 'Sắp xếp Designer' }), { target: { value: 'fix_asc' } })
    expect(names()).toEqual(['Hoa Trần', 'Quân Nguyễn'])
  })

  it('shows no Fix rates to anyone the page did not give them to', () => {
    render(
      <QuickDistributeModal isOpen onClose={mockOnClose} waitingOrders={mockWaitingOrders} designers={mockDesigners}
        onSuccess={mockOnSuccess} setFlash={mockSetFlash} />
    )
    expect(screen.queryByText(/Fix 30 ngày/)).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Sắp xếp Designer' })).not.toBeInTheDocument()
  })
})
