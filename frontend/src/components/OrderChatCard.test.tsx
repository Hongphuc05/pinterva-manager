import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { OrderChatCard } from './OrderChatCard'

const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), apiFetch: api.apiFetch }))

const message = (over: object) => ({
  id: 1, type: '', sender_type: 'staff', sender_name: 'Nguyễn Hữu Cường', mine: false, content: 'Bổ sung file JG nha',
  image_urls: [], fix_round: 0, fix_reason_label: '', sent_at: '2026-10-14T06:45:37Z', ...over,
})

beforeEach(() => {
  api.apiFetch.mockReset()
})

describe('order chat card', () => {
  it('shows both sides, marks the Fix round and marks the conversation read', async () => {
    api.apiFetch.mockImplementation((path: string) => {
      if (path.endsWith('/chat/read')) return Promise.resolve({})
      return Promise.resolve({
        stale: false, last_read_external_id: 0,
        messages: [message({ id: 5, type: 'fix_open', fix_round: 2 }), message({ id: 6, mine: true, sender_name: 'Support', content: 'đã bổ sung' })],
      })
    })
    render(<OrderChatCard orderId="o1" />)
    expect(await screen.findByText('Bổ sung file JG nha')).toBeInTheDocument()
    expect(screen.getByText('Fix vòng 2')).toBeInTheDocument()
    expect(screen.getByText('đã bổ sung')).toBeInTheDocument()
    await waitFor(() => expect(api.apiFetch).toHaveBeenCalledWith('/orders/o1/chat/read', { method: 'POST' }))
  })

  it('renders nothing when the user may not read this order chat', async () => {
    api.apiFetch.mockRejectedValue(new ApiError(403, 'Bạn không có quyền'))
    const { container } = render(<OrderChatCard orderId="o1" />)
    await waitFor(() => expect(api.apiFetch).toHaveBeenCalled())
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })
})
