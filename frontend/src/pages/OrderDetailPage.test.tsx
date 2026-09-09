import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { PlatformProvider } from '../auth/PlatformContext'
import { OrderDetailPage } from './OrderDetailPage'

describe('OrderDetailPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/api/orders/')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              order: {
                id: 'a1',
                external_order_id: 'DJ1',
                state: 'DISCOVERED',
                product_name: 'Test Mug',
                thumbnail_url: null,
                sku: 'SKU1',
                product_category: null,
                product_variants: null,
                has_template: false,
                multiple_design: false,
                double_sided: false,
                deadline_at_ext: null,
                note_outsource: '',
                order_note: '',
                custom_config: null,
                design_tool_url: null,
                created_at: '2026-01-01T00:00:00',
              },
              history: [],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })
    )
  })

  it('renders order fields', async () => {
    render(
      <AuthProvider>
        <PlatformProvider>
          <MemoryRouter initialEntries={['/orders/a1']}>
            <Routes>
              <Route path="/orders/:id" element={<OrderDetailPage />} />
            </Routes>
          </MemoryRouter>
        </PlatformProvider>
      </AuthProvider>
    )
    await waitFor(() => expect(screen.getByText(/Test Mug/)).toBeInTheDocument())
    expect(screen.getByText(/SKU1/)).toBeInTheDocument()
  })
})
