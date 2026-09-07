import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { KanbanPage } from './KanbanPage'

describe('KanbanPage', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: true, status: 200, json: async () => ({ columns: [{ id: 'attention', title: 'Cần xử lý', cards: [{
      id: 'o1', external_order_id: 'KAN-1', state: 'EXCEPTION', product_name: 'Mug', thumbnail_url: null,
      job_type: null, designer_name: 'Nam', deadline_at_ext: null, alerts: ['Exception'],
    }] }] }),
  }))))

  it('renders cards and their operational alerts', async () => {
    render(<BrowserRouter><KanbanPage /></BrowserRouter>)
    await waitFor(() => expect(screen.getByText('KAN-1')).toBeInTheDocument())
    expect(screen.getByText('Exception')).toBeInTheDocument()
    expect(screen.getByText(/Bảng chỉ đọc/)).toBeInTheDocument()
  })
})
