import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { PlatformProvider } from '../auth/PlatformContext'
import { ToastProvider } from '../context/ToastContext'
import { DesignerSubmissionsPage } from './DesignerSubmissionsPage'

afterEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('DesignerSubmissionsPage', () => {
  it('allows Support to open the product thumbnail in an image modal', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/api/me')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ id: 'support-1', role: 'support', full_name: 'Support User' }),
        })
      }
      if (url.includes('/api/platforms/current')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            id: 'platform-1',
            name: 'Acc Mẹ',
            account_username: 'support@example.com',
            is_active: true,
            created_at: '2026-09-23T00:00:00Z',
          }),
        })
      }
      if (url.includes('/api/orders/designer-submissions/designers')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [
            {
              id: 'designer-1',
              username: 'designer-one',
              full_name: 'Designer One',
              role: 'designer',
            },
          ],
        })
      }
      if (url.includes('/api/users')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => [] })
      }
      if (url.includes('/api/orders/designer-submissions')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            items: [
              {
                order_id: 'order-1',
                external_order_id: 'DJ-SUPPORT-1',
                product_name: 'Sản phẩm kiểm tra ảnh',
                thumbnail_url: 'https://assets.example.com/product-1.png',
                sku: null,
                designer_id: 'designer-1',
                designer_name: 'Designer One',
                designer_username: 'designer-one',
                first_submitted_at: '2026-09-23T00:00:00Z',
                latest_submitted_at: '2026-09-23T00:00:00Z',
                first_drive_url: 'https://drive.google.com/file/d/first/view',
                latest_drive_url: 'https://drive.google.com/file/d/first/view',
                versions: [],
                current_note_outsource: null,
                order_state: 'QC_PENDING',
                printerval_status: 'review',
                created_at: '2026-09-23T00:00:00Z',
              },
            ],
            total_items: 1,
            page: 1,
            page_size: 30,
            total_pages: 1,
            total_versions_count: 1,
            total_first_versions_count: 1,
          }),
        })
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <DesignerSubmissionsPage />
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>,
    )

    await waitFor(() => expect(screen.getByText('DJ-SUPPORT-1')).toBeInTheDocument())
    expect(screen.getByRole('option', { name: 'Designer One' })).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'designer-1' } })
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes('designer_id=designer-1'))).toBe(true)
    })

    fireEvent.click(screen.getByRole('button', { name: 'Xem ảnh sản phẩm DJ-SUPPORT-1' }))

    expect(screen.getByAltText('Ảnh sản phẩm')).toHaveAttribute(
      'src',
      'https://assets.example.com/product-1.png',
    )

    fireEvent.click(screen.getByTitle('Đóng (Esc)'))
    expect(screen.queryByAltText('Ảnh sản phẩm')).not.toBeInTheDocument()
  })
})
