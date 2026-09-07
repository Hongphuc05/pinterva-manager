import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
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
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (url.includes('/api/me')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ id: 'd1', role: 'designer', full_name: 'Nam' }),
        })
      }
      if (url.includes('/api/my-tasks')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ tasks: [activeTask] }) })
      }
      if (url.includes('/api/assignments/a1/results')) {
        expect(init?.method).toBe('POST')
        expect(init?.body).toContain('known-file')
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ assignment_id: 'a1', state: 'QC_PENDING', result_version_id: 'r1' }),
        })
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    }))
  })

  it('renders a designer task and submits its Drive link', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <MyTasksPage />
        </AuthProvider>
      </BrowserRouter>
    )

    await waitFor(() => expect(screen.getByText('TASK-1')).toBeInTheDocument())
    fireEvent.change(screen.getByPlaceholderText('Link Google Drive kết quả'), {
      target: { value: 'https://drive.google.com/file/d/known-file/view' },
    })
    fireEvent.click(screen.getByText('Nộp kết quả'))
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith('/api/assignments/a1/results', expect.anything())
    )
  })
})
