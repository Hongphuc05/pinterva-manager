import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiFetch, apiFetchBlob } = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  apiFetchBlob: vi.fn(),
}))

vi.mock('../api/client', () => ({ apiFetch, apiFetchBlob }))
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'admin', full_name: 'Admin' } }),
}))
vi.mock('./ImageModal', () => ({ ImageModal: () => null }))

import { OrderWorkNotesCard } from './OrderWorkNotesCard'

describe('OrderWorkNotesCard', () => {
  beforeEach(() => {
    apiFetch.mockReset()
    apiFetchBlob.mockReset()
    apiFetch.mockResolvedValueOnce({ notes: [] })
    vi.stubGlobal('crypto', { randomUUID: () => 'request-1' })
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:preview'),
      revokeObjectURL: vi.fn(),
    })
  })

  it('turns a pasted image into a preview and submits it with the note', async () => {
    render(<OrderWorkNotesCard orderId="order-1" />)
    await screen.findByText('Chưa có ghi chú làm việc.')

    const image = new File(['image'], 'copied.png', { type: 'image/png' })
    const clipboardData = {
      items: [{ type: 'image/png', getAsFile: () => image }],
    }
    const textarea = screen.getByPlaceholderText('Nhập ghi chú; Ctrl/Cmd + V để dán ảnh…')
    fireEvent.paste(textarea, { clipboardData })

    expect(screen.getByAltText('Ảnh chờ gửi')).toHaveAttribute('src', 'blob:preview')
    fireEvent.change(textarea, { target: { value: 'Đây là temp mới' } })
    apiFetch.mockResolvedValueOnce({
      id: 'note-1', body: 'Đây là temp mới', author_name: 'Admin', author_role: 'admin', created_at: '2026-09-20T00:00:00Z', attachments: [],
    })
    fireEvent.click(screen.getByRole('button', { name: 'Gửi cập nhật' }))

    await waitFor(() => expect(apiFetch).toHaveBeenLastCalledWith(
      '/orders/order-1/work-notes',
      expect.objectContaining({ method: 'POST', body: expect.any(FormData) }),
    ))
    const request = apiFetch.mock.calls.at(-1)?.[1] as RequestInit
    const form = request.body as FormData
    expect(form.get('body')).toBe('Đây là temp mới')
    const submittedImage = form.get('images') as File
    expect(submittedImage.name).toBe('copied.png')
    expect(submittedImage.type).toBe('image/png')
  })
})
