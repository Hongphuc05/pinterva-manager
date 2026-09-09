import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { PlatformProvider } from '../auth/PlatformContext'
import { MyTasksPage } from './MyTasksPage'

const activeTask = {
  assignment_id: 'a1', sub_status: 'doing', result_versions: [],
  order: {
    id: 'o1', external_order_id: 'TASK-1', state: 'IN_PROGRESS', product_name: 'Blue tee',
    thumbnail_url: null, sku: 'SKU-1', deadline_at_ext: null, order_note: 'Use blue',
    custom_config: null,
  },
}

describe('MyTasksPage', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { randomUUID: () => 'request-id' })
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.includes('/api/me')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ id: 'd1', role: 'designer', full_name: 'Nam' }),
        })
      }
      if (url.includes('/api/my-tasks')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ tasks: [activeTask] }) })
      }
      if (url.includes('/api/platforms')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    }))
  })

  it('renders basic designer task card with link to details page', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <MyTasksPage />
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )

    await waitFor(() => expect(screen.getByText('TASK-1')).toBeInTheDocument())
    expect(screen.getByText('Blue tee')).toBeInTheDocument()
    const detailLink = screen.getByRole('link', { name: /Xem Chi Tiết & Nộp Bài/i })
    expect(detailLink).toHaveAttribute('href', '/orders/o1')
  })
})

