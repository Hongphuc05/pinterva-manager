import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { PlatformProvider } from '../auth/PlatformContext'
import { GallerySyncProvider } from '../context/GallerySyncContext'
import { DuplicateBoardPage } from './DuplicateBoardPage'

describe('DuplicateBoardPage', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'admin-1', role: 'admin', full_name: 'Admin' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/duplicate-board')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              cross_designer_drag_enabled: true,
              columns: [
                {
                  id: 'orders',
                  title: 'Đơn hàng',
                  column_type: 'orders',
                  metrics: { total: 1, doing: 1, review: 0, fix: 0, done: 0 },
                  cards: [{
                    id: 'order-1',
                    external_order_id: 'DJ-DUP-1',
                    product_name: 'Áo trùng lặp 1',
                    thumbnail_url: null,
                    deadline_at_ext: null,
                    state: 'IN_PROGRESS',
                    note_outsource: '',
                    previous_note_outsource: null,
                    fix_approved_by_admin: false,
                    assignee_id: null,
                    assignee_name: null,
                    is_paid: false,
                    template_missing: false,
                  }],
                },
                {
                  id: 'missing_form',
                  title: 'Thiếu form',
                  column_type: 'missing_form',
                  metrics: { total: 0, doing: 0, review: 0, fix: 0, done: 0 },
                  cards: [],
                },
                {
                  id: 'trello-1',
                  title: 'Trello Designer Phúc',
                  column_type: 'designer',
                  metrics: { total: 1, doing: 1, review: 0, fix: 0, done: 0 },
                  cards: [{
                    id: 'order-2',
                    external_order_id: 'DJ-DUP-2',
                    product_name: 'Áo đang làm',
                    thumbnail_url: null,
                    deadline_at_ext: null,
                    state: 'IN_PROGRESS',
                    note_outsource: '',
                    previous_note_outsource: null,
                    fix_approved_by_admin: false,
                    assignee_id: 'trello-1',
                    assignee_name: 'Trello Designer Phúc',
                    is_paid: false,
                    template_missing: false,
                  }],
                },
                {
                  id: 'done',
                  title: 'Done',
                  column_type: 'done',
                  metrics: { total: 2, doing: 0, review: 0, fix: 0, done: 2 },
                  cards: [
                    {
                      id: 'order-3',
                      external_order_id: 'DJ-DONE-1',
                      product_name: 'Áo đã xong chưa TT',
                      thumbnail_url: null,
                      deadline_at_ext: null,
                      state: 'DONE',
                      note_outsource: '',
                      previous_note_outsource: null,
                      fix_approved_by_admin: false,
                      assignee_id: 'trello-1',
                      assignee_name: 'Trello Designer Phúc',
                      is_paid: false,
                      template_missing: false,
                      status_changed_at: '2026-09-17T12:00:00',
                    },
                    {
                      id: 'order-4',
                      external_order_id: 'DJ-DONE-2',
                      product_name: 'Áo đã xong đã TT',
                      thumbnail_url: null,
                      deadline_at_ext: null,
                      state: 'DONE',
                      note_outsource: '',
                      previous_note_outsource: null,
                      fix_approved_by_admin: false,
                      assignee_id: 'trello-2',
                      assignee_name: 'Trello Designer Hoàng',
                      is_paid: true,
                      template_missing: false,
                      status_changed_at: '2026-09-17T14:00:00',
                    },
                  ],
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }),
    )
  })

  it('renders all 4 column groups: Đơn hàng, Thiếu form, Designer columns, and Done', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <GallerySyncProvider>
              <DuplicateBoardPage />
            </GallerySyncProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>,
    )

    await waitFor(() => expect(screen.getByText('DJ-DUP-1')).toBeInTheDocument())
    expect(screen.getByRole('heading', { name: 'Đơn hàng' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Thiếu form' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Trello Designer Phúc' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Done' })).toBeInTheDocument()

    expect(screen.getByText('Áo trùng lặp 1')).toBeInTheDocument()
    expect(screen.getByText('Áo đang làm')).toBeInTheDocument()
    expect(screen.getByText('Áo đã xong chưa TT')).toBeInTheDocument()
    expect(screen.getByText('Áo đã xong đã TT')).toBeInTheDocument()

    for (const columnTitle of ['Đơn hàng', 'Thiếu form', 'Trello Designer Phúc', 'Done']) {
      expect(screen.getByLabelText(`Danh sách đơn của ${columnTitle}`)).toHaveClass('overflow-y-auto')
    }
  })

  it('filters Done cards by payment status and designer', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <GallerySyncProvider>
              <DuplicateBoardPage />
            </GallerySyncProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>,
    )

    await waitFor(() => expect(screen.getByText('DJ-DONE-1')).toBeInTheDocument())
    expect(screen.getByText('DJ-DONE-2')).toBeInTheDocument()

    // Filter by payment: "Đã thanh toán"
    const paymentSelect = screen.getByDisplayValue('Tất cả thanh toán')
    fireEvent.change(paymentSelect, { target: { value: 'paid' } })

    // Only DJ-DONE-2 should show
    expect(screen.queryByText('DJ-DONE-1')).not.toBeInTheDocument()
    expect(screen.getByText('DJ-DONE-2')).toBeInTheDocument()

    // Filter by designer: "Trello Designer Phúc" in Done column
    const designerSelects = screen.getAllByDisplayValue(/Tất cả Designer/)
    const doneDesignerSelect = designerSelects[designerSelects.length - 1]
    fireEvent.change(doneDesignerSelect, { target: { value: 'trello-1' } })

    // Since DJ-DONE-2 is by trello-2 and DJ-DONE-1 is unpaid, neither should show
    expect(screen.queryByText('DJ-DONE-2')).not.toBeInTheDocument()
    expect(screen.getByText('Chưa có đơn hoàn thành')).toBeInTheDocument()

    // Switch payment back to all
    fireEvent.change(paymentSelect, { target: { value: 'all' } })
    // DJ-DONE-1 should now show
    expect(screen.getByText('DJ-DONE-1')).toBeInTheDocument()
  })

  it('filters cards with global search input', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <GallerySyncProvider>
              <DuplicateBoardPage />
            </GallerySyncProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>,
    )

    await waitFor(() => expect(screen.getByText('DJ-DUP-1')).toBeInTheDocument())
    expect(screen.getByText('DJ-DUP-2')).toBeInTheDocument()

    // Type in global search
    const searchInput = screen.getByPlaceholderText('Tìm mã đơn, tên sản phẩm...')
    fireEvent.change(searchInput, { target: { value: 'DJ-DUP-2' } })

    expect(screen.queryByText('DJ-DUP-1')).not.toBeInTheDocument()
    expect(screen.getByText('DJ-DUP-2')).toBeInTheDocument()

    // Clear search
    fireEvent.change(searchInput, { target: { value: '' } })
    expect(screen.getByText('DJ-DUP-1')).toBeInTheDocument()
    expect(screen.getByText('DJ-DUP-2')).toBeInTheDocument()
  })
})
