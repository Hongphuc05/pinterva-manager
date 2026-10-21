import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DesignerFixModal, FixStatsLine, type DesignerFixStat } from './DesignerFixStats'

const stat = (over: Partial<DesignerFixStat> = {}): DesignerFixStat => ({
  designer_id: 'des-a', submitted_orders: 5, fixed_orders: 1, fix_rate: 20, fix_count: 3, max_fixes_per_order: 3,
  repeat_orders: 1, distribution: { '1': 0, '2': 0, '3+': 1 }, excluded: { fake: 0, admin_rejected: 0 }, ...over,
})

describe('FixStatsLine', () => {
  it('shows the rate per order and calls out an order Fixed three times', () => {
    const onDetail = vi.fn()
    render(<FixStatsLine stat={stat()} threshold={3} onDetail={onDetail} />)

    expect(screen.getByText('1/5 đơn (20%)')).toBeInTheDocument()
    expect(screen.getByText(/3 lượt Fix/)).toBeInTheDocument()
    expect(screen.getByText('1 đơn bị Fix ≥3 lần (nhiều nhất 3 lần)')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Chi tiết Fix' }))
    expect(onDetail).toHaveBeenCalled()
  })

  it('has no warning when no order came back three times, and says when nothing was submitted', () => {
    const { rerender } = render(<FixStatsLine stat={stat({ fix_count: 1, max_fixes_per_order: 1, repeat_orders: 0 })} threshold={3} onDetail={vi.fn()} />)
    expect(screen.queryByText(/≥3 lần/)).not.toBeInTheDocument()
    rerender(<FixStatsLine stat={undefined} threshold={3} onDetail={vi.fn()} />)
    expect(screen.getByText(/chưa có đơn nộp/)).toBeInTheDocument()
  })
})

describe('DesignerFixModal', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({
        orders: [{
          order_id: 'o1', external_order_id: 'DJ1', product_name: 'Áo DJ1', thumbnail_url: null,
          first_submitted_at: '2026-10-13T03:00:00Z', fix_count: 3,
          fixes: [
            { at: '2026-10-13T04:00:00Z', reason: 'Lỗi làm khác mockup gốc', excluded: null },
            { at: '2026-10-13T06:00:00Z', reason: null, excluded: 'fake' },
          ],
        }],
      }),
    })))
  })

  it("lists the Designer's Fixed orders for the chosen period, each Fix with its reason", async () => {
    render(
      <MemoryRouter>
        <DesignerFixModal designerId="des-a" name="An" range={{ from: '2026-10-12', to: '2026-10-18' }} threshold={3} onClose={vi.fn()} />
      </MemoryRouter>,
    )
    expect(await screen.findByText('DJ1')).toBeInTheDocument()
    expect(screen.getByText('Fix 3 lần')).toBeInTheDocument()
    expect(screen.getByText(/Lỗi làm khác mockup gốc/)).toBeInTheDocument()
    expect(screen.getByText(/Fix giả \(lỗi đồng bộ\), không tính/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Mở đơn/ })).toHaveAttribute('href', '/orders/o1')
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/api/designers/des-a/fix-stats?date_from=2026-10-12&date_to=2026-10-18', expect.anything(),
    ))
  })
})
