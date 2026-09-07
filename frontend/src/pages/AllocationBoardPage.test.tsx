import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { AllocationBoardPage } from './AllocationBoardPage'

describe('AllocationBoardPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({ id: '1', role: 'admin', full_name: 'Admin' }),
          })
        }
        if (url.includes('/api/allocation/board')) {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              unassigned: [
                { id: 'o1', external_order_id: 'DJ1', thumbnail_url: null, sku: 'SKU1', deadline_at_ext: null },
              ],
              designers: [{ id: 'd1', full_name: 'Nam', capacity: 5, held: 0, pending_approvals: [] }],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })
    )
  })

  it('loads and renders the board after entering a batch id', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <AllocationBoardPage />
        </AuthProvider>
      </BrowserRouter>
    )
    fireEvent.change(screen.getByPlaceholderText('Batch ID'), { target: { value: 'b1' } })
    fireEvent.click(screen.getByText('Tải'))
    await waitFor(() => expect(screen.getByText('DJ1')).toBeInTheDocument())
    expect(screen.getByText(/Nam/)).toBeInTheDocument()
  })
})
