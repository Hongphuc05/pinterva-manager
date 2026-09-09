import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { PlatformProvider } from '../auth/PlatformContext'
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
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
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
          <PlatformProvider>
            <AllocationBoardPage />
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )
    fireEvent.change(screen.getByPlaceholderText(/Batch ID/i), { target: { value: 'b1' } })
    fireEvent.click(screen.getByRole('button', { name: /Tải Bảng/i }))
    await waitFor(() => expect(screen.getByText('DJ1')).toBeInTheDocument())
    expect(screen.getByText(/Nam/)).toBeInTheDocument()
  })

  it('lets the logged-in designer offer a quantity', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes('/api/me')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ id: 'd1', role: 'designer', full_name: 'Nam' }),
        })
      }
      if (url.includes('/api/platforms')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
      }
      if (url.includes('/api/allocation/offer')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ granted_order_ids: ['DJ1'], assignment_ids: ['a1'] }),
        })
      }
      if (url.includes('/api/allocation/board')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            unassigned: [],
            designers: [{ id: 'd1', full_name: 'Nam', capacity: 5, held: 0, pending_approvals: [] }],
          }),
        })
      }
      return Promise.reject(new Error(`unexpected fetch: ${url} ${init?.method}`))
    })

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <AllocationBoardPage />
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )
    fireEvent.change(screen.getByPlaceholderText(/Batch ID/i), { target: { value: 'b1' } })
    fireEvent.click(screen.getByRole('button', { name: /Tải Bảng/i }))
    await waitFor(() => expect(screen.getByText('Đăng ký nhận')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Đăng ký nhận'))
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith('/api/allocation/offer', expect.anything())
    )
  })

  it('names the admin and time when a decision was already made', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/api/me')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ id: 'a2', role: 'admin', full_name: 'Second admin' }),
        })
      }
      if (url.includes('/api/platforms')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
      }
      if (url.includes('/api/approvals/ap1/decide')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            decided_by_me: false, decided_by_name: 'First admin',
            decided_at: '2026-09-07T16:00:00Z',
          }),
        })
      }
      if (url.includes('/api/allocation/board')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            unassigned: [],
            designers: [{
              id: 'd1', full_name: 'Nam', capacity: 5, held: 1,
              pending_approvals: [{
                approval_id: 'ap1',
                order: {
                  id: 'o1', external_order_id: 'DJ1', thumbnail_url: null,
                  sku: 'SKU1', deadline_at_ext: null,
                },
              }],
            }],
          }),
        })
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <AllocationBoardPage />
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )
    fireEvent.change(screen.getByPlaceholderText(/Batch ID/i), { target: { value: 'b1' } })
    fireEvent.click(screen.getByRole('button', { name: /Tải Bảng/i }))
    await waitFor(() => expect(screen.getByText('Duyệt')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Duyệt'))
    await waitFor(() => expect(screen.getByText(/First admin/)).toBeInTheDocument())
  })
})

