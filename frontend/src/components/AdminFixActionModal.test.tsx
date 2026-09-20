import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AdminFixActionModal } from './AdminFixActionModal'

describe('AdminFixActionModal', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, note_outsource: 'QC note approved by admin' }),
    })))
  })

  it('copies the approved outsource note to the designer when admin note is blank', async () => {
    const onSuccess = vi.fn()
    render(
      <AdminFixActionModal
        isOpen
        mode="approve"
        orderId="order-1"
        orderVersion={4}
        externalOrderId="DJ-FIX-1"
        currentNote="QC note approved by admin"
        onClose={vi.fn()}
        onSuccess={onSuccess}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Xác Nhận & Giao Des' }))

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        '/api/orders/order-1/approve-fix',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            designer_note: '',
            note_outsource: 'QC note approved by admin',
            expected_version: 4,
          }),
        }),
      )
      expect(onSuccess).toHaveBeenCalledWith('QC note approved by admin')
    })
  })
})
