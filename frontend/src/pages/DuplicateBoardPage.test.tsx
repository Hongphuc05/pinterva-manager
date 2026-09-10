import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { PlatformProvider } from '../auth/PlatformContext'
import { DuplicateBoardPage } from './DuplicateBoardPage'

describe('DuplicateBoardPage', () => {
  beforeEach(() => {
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
                  id: 'unassigned',
                  title: 'Thiếu form',
                  metrics: { total: 1, doing: 0, review: 0, fix: 0, done: 0 },
                  cards: [{
                    id: 'order-1',
                    external_order_id: 'DJ-DUP-1',
                    product_name: 'Áo trùng lặp',
                    thumbnail_url: null,
                    deadline_at_ext: null,
                    state: 'WAITING',
                    note_outsource: '',
                    previous_note_outsource: null,
                    fix_approved_by_admin: false,
                    assignee_id: null,
                    assignee_name: null,
                  }],
                },
                {
                  id: 'trello-1',
                  title: 'Designer Trello',
                  metrics: { total: 0, doing: 0, review: 0, fix: 0, done: 0 },
                  cards: [],
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }),
    )
  })

  it('renders the missing-form and designer columns returned by the board API', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <DuplicateBoardPage />
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>,
    )

    await waitFor(() => expect(screen.getByText('DJ-DUP-1')).toBeInTheDocument())
    expect(screen.getByText('Thiếu form')).toBeInTheDocument()
    expect(screen.getByText('Designer Trello')).toBeInTheDocument()
    expect(screen.getByText('Áo trùng lặp')).toBeInTheDocument()
    expect(screen.getAllByText('Doing 0')).toHaveLength(2)
    expect(screen.getAllByText('Done 0')).toHaveLength(2)
  })
})
