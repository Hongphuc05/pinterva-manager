import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AdminFixActionModal } from './AdminFixActionModal'

describe('AdminFixActionModal', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve({
      ok: true,
      status: 200,
      json: async () => (url.endsWith('/fix-chat')
        ? { text: 'Đổi template — Dùng temp adult' }
        : { ok: true, note_outsource: 'https://drive.google.com/ours' }),
    })))
  })

  it('shows the Fix from the chat and lets the backend copy it when the admin note is blank', async () => {
    const onSuccess = vi.fn()
    render(
      <AdminFixActionModal
        isOpen
        mode="approve"
        orderId="order-1"
        orderVersion={4}
        externalOrderId="DJ-FIX-1"
        currentNote="https://drive.google.com/ours"
        onClose={vi.fn()}
        onSuccess={onSuccess}
      />,
    )

    expect(await screen.findByText('Đổi template — Dùng temp adult')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Xác Nhận & Giao Des' }))

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        '/api/orders/order-1/approve-fix',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ designer_note: '', expected_version: 4 }),
        }),
      )
      expect(onSuccess).toHaveBeenCalled()
    })
  })
})
