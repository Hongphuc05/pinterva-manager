import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { PlatformProvider } from '../auth/PlatformContext'
import { KanbanPage } from './KanbanPage'

describe('KanbanPage', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (url.includes('/api/me')) {
      return Promise.resolve({
        ok: true, status: 200, json: async () => ({ id: '1', role: 'admin', full_name: 'Admin' }),
      })
    }
    if (url.includes('/api/platforms')) {
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
    }
    return Promise.resolve({
      ok: true, status: 200, json: async () => ({ columns: [{ id: 'attention', title: 'Cần xử lý', cards: [{
        id: 'o1', external_order_id: 'KAN-1', state: 'EXCEPTION', product_name: 'Mug', thumbnail_url: null,
        job_type: null, designer_name: 'Nam', deadline_at_ext: null,
        alerts: [{ kind: 'exception', label: 'Exception', detail: 'Critical exception', occurred_at: null }],
      }] }] }),
    })
  })))

  it('renders cards and their operational alerts', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <KanbanPage />
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )
    await waitFor(() => expect(screen.getByText('KAN-1')).toBeInTheDocument())
    expect(screen.getByText('Exception')).toBeInTheDocument()
  })
})


