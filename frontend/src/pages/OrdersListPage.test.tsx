import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { OrdersListPage } from './OrdersListPage'

describe('OrdersListPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: '1', role: 'admin', full_name: 'Admin' }),
          })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'a1',
                  external_order_id: 'DJ1',
                  state: 'DISCOVERED',
                  batch_id: null,
                  sku: 'SKU1',
                  thumbnail_url: null,
                  deadline_at_ext: null,
                  created_at: '2026-01-01T00:00:00',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })
    )
  })

  it('renders orders from the API', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <OrdersListPage />
        </AuthProvider>
      </BrowserRouter>
    )
    await waitFor(() => expect(screen.getByText('DJ1')).toBeInTheDocument())
    expect(screen.getByText('SKU1')).toBeInTheDocument()
  })
})
