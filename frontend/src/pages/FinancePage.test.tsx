import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import { FinancePage } from './FinancePage'
import { AuthProvider } from '../auth/AuthContext'
import { PlatformProvider } from '../auth/PlatformContext'
import { ToastProvider } from '../context/ToastContext'
import { GallerySyncProvider } from '../context/GallerySyncContext'

describe('FinancePage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders stats, 2-line date format, and switches to notes sub-tab', async () => {
    // The modal defaults to the current week. Keep the fixture inside that
    // range so the assertion does not depend on the calendar date in CI.
    const submittedAt = new Date().toISOString()
    const fetchMock = vi.fn((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'admin1', role: 'admin', full_name: 'Admin User' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/finance/stats')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              total_credited_tasks: 5,
              total_designers: 1,
              total_done_tasks: 3,
              total_in_review_tasks: 1,
              total_in_fix_tasks: 1,
              designers_summary: [
                {
                  designer_id: 'des1',
                  designer_name: 'Designer Thuý Hường',
                  username: 'huong_des',
                  total_tasks: 5,
                  in_review_tasks: 1,
                  in_fix_tasks: 1,
                  done_tasks: 3,
                  first_submission_at: submittedAt,
                  latest_submission_at: submittedAt,
                  notes_count: 2,
                },
              ],
              tasks: [
                {
                  order_id: 'ord1',
                  external_order_id: 'PRN-99881',
                  product_name: 'Vintage T-Shirt Design',
                  thumbnail_url: null,
                  designer_id: 'des1',
                  designer_name: 'Designer Thuý Hường',
                  current_state: 'DONE',
                  platform_status: 'done',
                  drive_link: 'https://drive.google.com/file/d/test1234/view',
                  placeholder_filled: true,
                  status_changed_at: submittedAt,
                  first_submitted_at: submittedAt,
                  latest_submitted_at: submittedAt,
                  submission_count: 1,
                  order_created_at: '2026-09-10T07:00:00Z',
                  notes_count: 1,
                },
              ],
              total_tasks_count: 1,
              page: 1,
              page_size: 50,
              total_pages: 1,
            }),
          })
        }
        if (url.includes('/api/finance/notes')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              notes: [
                {
                  id: 'note-1',
                  target_type: 'order',
                  order_id: 'ord1',
                  order_code: 'PRN-99881',
                  designer_id: null,
                  designer_name: null,
                  author_id: 'admin1',
                  author_name: 'Admin User',
                  content: 'Đơn này cần chú ý màu sắc in lụa',
                  created_at: '2026-09-11T03:00:00Z',
                  updated_at: '2026-09-11T03:00:00Z',
                },
              ],
              total: 1,
              page: 1,
              page_size: 50,
              total_pages: 1,
            }),
          })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
      })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <FinancePage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )

    await waitFor(() => expect(screen.getByText('Quản Lý Tài Chính & Công Lao Designer')).toBeInTheDocument())

    // Check KPI and Designer summary
    await waitFor(() => expect(screen.getAllByText('Designer Thuý Hường').length).toBeGreaterThan(0))
    expect(screen.getAllByText('Designer Thuý Hường').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('5 công')).toBeInTheDocument()

    // Click "Xem đơn" to open Designer Finance Detail Modal
    const xemDonBtn = screen.getByText('Xem đơn')
    fireEvent.click(xemDonBtn)

    // Modal should now be open
    await waitFor(() => expect(screen.getByText('PRN-99881')).toBeInTheDocument())
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => (
      String(url).includes('/api/finance/stats')
      && String(url).includes('designer_id=des1')
      && String(url).includes('page_size=50')
    ))).toBe(true))
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('page_size=1000'))).toBe(false)
    expect(screen.getAllByText('Vintage T-Shirt Design').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('40.000 đ').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('Tổng số tiền trong tuần (Chưa thanh toán):')).toBeInTheDocument()

    // Test Rate Stepper: increase rate by 5,000
    const plusBtn = screen.getByTitle('Tăng 5,000 đ')
    fireEvent.click(plusBtn)
    expect(screen.getAllByText('45.000 đ').length).toBeGreaterThanOrEqual(2)

    // Close modal
    const closeBtn = screen.getByTitle('Đóng popup')
    fireEvent.click(closeBtn)

    // Switch to Notes sub-tab
    const notesTabBtn = screen.getByText('Ghi Chú Admin (Notes)')
    fireEvent.click(notesTabBtn)

    await waitFor(() => expect(screen.getByText('Đơn này cần chú ý màu sắc in lụa')).toBeInTheDocument())
    expect(screen.getByText('Tạo Ghi Chú Mới')).toBeInTheDocument()
  })

  it('shows Support only its classification count and does not request payment finance', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/api/me')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ id: 'support1', role: 'support', full_name: 'Support User' }),
        })
      }
      if (url.includes('/api/platforms')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
      }
      if (url.includes('/api/finance/stats')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            total_credited_tasks: 0,
            total_unpaid_tasks: 0,
            total_paid_tasks: 0,
            total_designers: 0,
            total_done_tasks: 0,
            total_in_review_tasks: 0,
            total_in_fix_tasks: 0,
            designers_summary: [],
            tasks: [],
            total_tasks_count: 0,
            page: 1,
            page_size: 50,
            total_pages: 1,
            support_classified_count: 7,
            support_summary: [{
              support_id: 'support1',
              support_name: 'Support User',
              username: 'support_user',
              classified_tasks: 7,
              first_classified_at: null,
              latest_classified_at: null,
            }],
            support_orders: [
              { id: 'o1', external_order_id: 'DJ4048241', product_name: 'Wests Tigers Jersey', thumbnail_url: null, classified_at: '2026-09-24T10:03:00Z' },
              { id: 'o2', external_order_id: 'DJ4033320', product_name: 'Atlanta Falcons Dress', thumbnail_url: 'https://cdn.test/a.png', classified_at: '2026-09-23T08:00:00Z' },
            ],
          }),
        })
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    window.history.pushState({}, '', '/finance')

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <FinancePage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>,
    )

    await waitFor(() => expect(screen.getByText('Công Việc Phân Loại Của Tôi')).toBeInTheDocument())
    expect(screen.getByText('Tổng đơn đã phân loại')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('7')).toBeInTheDocument())
    // The orders behind the count are listed (newest first), and can be filtered.
    expect(screen.getByText('Chi tiết các đơn đã gắn Trùng lặp')).toBeInTheDocument()
    expect(screen.getByText('DJ4048241')).toBeInTheDocument()
    expect(screen.getByText('Atlanta Falcons Dress')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Tìm trong các đơn đã gắn Trùng lặp'), { target: { value: 'falcons' } })
    expect(screen.queryByText('DJ4048241')).not.toBeInTheDocument()
    expect(screen.getByText('DJ4033320')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Tìm trong các đơn đã gắn Trùng lặp'), { target: { value: 'zzz' } })
    expect(screen.getByText('Không có đơn nào khớp.')).toBeInTheDocument()
    expect(screen.queryByText('Tổng Đơn Tính Công')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/api/finance/stats') && String(url).includes('is_paid='))).toBe(false)
  })
})
