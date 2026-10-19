import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('../api/client', () => ({ apiFetch: api.apiFetch }))

import { PrintervalChatCard } from './PrintervalChatCard'

const message = (over: Record<string, unknown>) => ({
  id: 1, fix_round: 0, type: 'message', sender_name: 'QC An', mine: false, content: '', image_urls: [],
  fix_reason_label: '', sent_at: '2026-10-19T07:05:10+00:00', ...over,
})

describe('PrintervalChatCard', () => {
  beforeEach(() => api.apiFetch.mockReset())

  it('shows the conversation with the Fix round, reason and who wrote what', async () => {
    api.apiFetch.mockResolvedValueOnce({
      messages: [
        message({ id: 1, type: 'fix_open', fix_round: 2, fix_reason_label: 'Sai màu', content: 'Sửa phần tay áo' }),
        message({ id: 2, mine: true, content: 'Đã nhận' }),
      ],
    })
    render(<PrintervalChatCard orderId="o1" />)

    expect(await screen.findByText('Sửa phần tay áo')).toBeInTheDocument()
    expect(screen.getByText('Mở Fix vòng 2')).toBeInTheDocument()
    expect(screen.getByText('Sai màu')).toBeInTheDocument()
    expect(screen.getByText('Đã nhận')).toBeInTheDocument()
    expect(api.apiFetch).toHaveBeenCalledWith('/orders/o1/printerval-chat')
  })

  it('says so when Printerval cannot be reached and loads again on request', async () => {
    api.apiFetch.mockRejectedValueOnce(new Error('Không tải được chat từ Printerval, thử lại sau'))
    api.apiFetch.mockResolvedValueOnce({ messages: [] })
    render(<PrintervalChatCard orderId="o1" />)

    expect(await screen.findByText('Không tải được chat từ Printerval, thử lại sau')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Tải lại/ }))
    expect(await screen.findByText('Chưa có tin nhắn nào.')).toBeInTheDocument()
  })
})
