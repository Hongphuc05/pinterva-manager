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
})
