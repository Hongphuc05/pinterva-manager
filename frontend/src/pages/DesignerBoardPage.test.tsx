import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { PlatformProvider } from '../auth/PlatformContext'
import { GallerySyncProvider } from '../context/GallerySyncContext'
import { ToastProvider } from '../context/ToastContext'
import { DesignerBoardPage } from './DesignerBoardPage'

describe('DesignerBoardPage', () => {
  let revokeRequestBody: unknown = null

  beforeEach(() => {
    localStorage.clear()
    revokeRequestBody = null
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.stubGlobal('alert', vi.fn())
    vi.stubGlobal('fetch', vi.fn((url: string, options?: RequestInit) => {
      if (url.includes('/api/me')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ id: 'admin-1', role: 'admin', full_name: 'Admin' }) })
      }
      if (url.includes('/api/platforms')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
      }
      if (url.includes('/api/designers/workload')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [
            {
              id: 'designer-fix', username: 'fix', full_name: 'Designer Có Fix', total_orders: 2, doing_count: 1, review_count: 0, fix_count: 1, done_count: 0,
              orders: [{
                id: 'order-remove-1', version: 7, external_order_id: 'DJ-REMOVE-1', state: 'IN_PROGRESS', thumbnail_url: null,
                deadline_tacahu: null, product_name: 'Đơn cần gỡ', work_domain: 'standard',
              }],
            },
            { id: 'designer-idle', username: 'idle', full_name: 'Designer Rảnh', total_orders: 0, doing_count: 0, review_count: 0, fix_count: 0, done_count: 0, orders: [] },
          ],
        })
      }
      if (url.includes('/api/assignments/revoke')) {
        revokeRequestBody = JSON.parse(String(options?.body))
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ message: 'Đã hủy chia đơn thành công cho 1 đơn hàng.' }),
        })
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    }))
  })

  it('applies team filters and persists display choices', async () => {
    render(
      <BrowserRouter>
        <AuthProvider><PlatformProvider><ToastProvider><GallerySyncProvider><DesignerBoardPage /></GallerySyncProvider></ToastProvider></PlatformProvider></AuthProvider>
      </BrowserRouter>,
    )

    await screen.findByText('Designer Có Fix')
    fireEvent.click(screen.getByRole('button', { name: /Có đơn Fix/i }))

    expect(screen.getByRole('button', { name: /Có đơn Fix/i })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('Designer Có Fix')).toBeInTheDocument()
    expect(screen.queryByText('Designer Rảnh')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Ẩn Cột Done/i }))
    await waitFor(() => {
      const state = JSON.parse(localStorage.getItem('tacahu:view-state:v1:designer-board:admin') || '{}')
      expect(state.filterMode).toBe('has_fix')
      expect(state.showDoneColumn).toBe(false)
    })
  })

  it('lets an admin revoke a Doing order from the designer board', async () => {
    render(
      <BrowserRouter>
        <AuthProvider><PlatformProvider><ToastProvider><GallerySyncProvider><DesignerBoardPage /></GallerySyncProvider></ToastProvider></PlatformProvider></AuthProvider>
      </BrowserRouter>,
    )

    await screen.findByText('Designer Có Fix')
    fireEvent.click(screen.getByText('Designer Có Fix'))
    const removeButton = await screen.findByRole('button', { name: 'Gỡ đơn DJ-REMOVE-1 khỏi Designer' })
    fireEvent.click(removeButton)

    await waitFor(() => {
      expect(revokeRequestBody).toEqual({
        order_ids: ['order-remove-1'],
        expected_versions: { 'order-remove-1': 7 },
      })
    })
  })
})
