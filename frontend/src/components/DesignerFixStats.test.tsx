import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DesignerFixModal, FixStatsLine, MyFixRateCard, fixRateLabel, sortByFix, type DesignerFixStat } from './DesignerFixStats'

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

describe('fixRateLabel and sortByFix (designer pickers when splitting orders)', () => {
  it('labels the rate and warns about orders Fixed three times', () => {
    expect(fixRateLabel(stat(), 3)).toBe('Fix 20% (1/5) ⚠ 1 đơn Fix ≥3 lần')
    expect(fixRateLabel(stat({ repeat_orders: 0 }), 3)).toBe('Fix 20% (1/5)')
    expect(fixRateLabel(undefined)).toBe('Fix: chưa có đơn')
  })

  it('sorts by rate either way, Designers without orders last', () => {
    const list = [{ id: 'a' }, { id: 'none' }, { id: 'b' }]
    const stats = new Map([['a', stat({ designer_id: 'a', fix_rate: 40 })], ['b', stat({ designer_id: 'b', fix_rate: 10 })]])
    expect(sortByFix(list, stats, 'name').map((d) => d.id)).toEqual(['a', 'none', 'b'])
    expect(sortByFix(list, stats, 'fix_asc').map((d) => d.id)).toEqual(['b', 'a', 'none'])
    expect(sortByFix(list, stats, 'fix_desc').map((d) => d.id)).toEqual(['a', 'b', 'none'])
  })
})

describe('MyFixRateCard (the Designer\'s own rate on My Tasks)', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({
        incomplete: false, since: '2026-09-21', repeat_threshold: 3,
        summary: stat(),
        previous: stat({ fixed_orders: 3, submitted_orders: 10, fix_rate: 30 }),
        orders: [{
          order_id: 'o1', external_order_id: 'DJ1', product_name: 'Áo DJ1', thumbnail_url: null,
          first_submitted_at: '2026-10-13T03:00:00Z', fix_count: 3,
          fixes: [{ at: '2026-10-13T04:00:00Z', reason: 'Lỗi làm khác mockup gốc', excluded: null }],
        }],
      }),
    })))
  })

  it('shows their rate, whether it improved on the period before, and their Fixed orders', async () => {
    render(<MemoryRouter><MyFixRateCard /></MemoryRouter>)

    expect(await screen.findByText('20%')).toBeInTheDocument()
    expect(screen.getByText('1/5 đơn bị Fix · 3 lượt Fix')).toBeInTheDocument()
    expect(screen.getByText('▼ 10 điểm so với 30 ngày trước (30%)')).toBeInTheDocument()
    expect(screen.getByText('1 đơn bị Fix ≥3 lần')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith(expect.stringMatching(/^\/api\/my\/fix-stats\?date_from=\d{4}-\d{2}-\d{2}&date_to=/), expect.anything())

    fireEvent.click(screen.getByRole('button', { name: 'Xem đơn bị Fix' }))
    expect(await screen.findByText('DJ1')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledTimes(1)  // the orders came with the card
    expect(document.body.textContent?.toLowerCase()).not.toContain('printerval')
  })
})
