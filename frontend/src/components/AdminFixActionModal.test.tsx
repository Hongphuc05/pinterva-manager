import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AdminFixActionModal } from './AdminFixActionModal'

describe('AdminFixActionModal', () => {
  let templateRequest: unknown = null

  beforeEach(() => {
    templateRequest = null
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve({
      ok: true,
      status: 200,
      json: async () => (url.endsWith('/fix-chat')
        ? { text: 'Đổi template — Dùng temp adult' }
        : url.endsWith('/fix-template')
          ? { request: templateRequest }
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

  describe('when Printerval asks whether the Fix is about the template', () => {
    const renderModal = (onSuccess = vi.fn()) =>
      render(
        <AdminFixActionModal
          isOpen mode="approve" orderId="order-1" orderVersion={4} externalOrderId="DJ-FIX-1"
          currentNote="" onClose={vi.fn()} onSuccess={onSuccess}
        />,
      )
    const approvals = () => (fetch as any).mock.calls.filter((call: unknown[]) => String(call[0]).endsWith('/approve-fix'))

    beforeEach(() => {
      templateRequest = { round: 1, url: 'https://drive.test/tpl', note: 'Vneck' }
    })

    it('does not accept the Fix until the question is answered, and sends the answer with it', async () => {
      renderModal()
      expect(await screen.findByText('Vneck')).toBeTruthy()

      fireEvent.click(screen.getByRole('button', { name: 'Xác Nhận & Giao Des' }))
      expect((await screen.findAllByText(/có phải do đổi template/)).length).toBeGreaterThan(0)
      expect(approvals()).toHaveLength(0)

      fireEvent.click(screen.getByRole('button', { name: 'Xác nhận Fix do đổi template' }))
      fireEvent.click(screen.getByRole('button', { name: 'Xác Nhận & Giao Des' }))
      await waitFor(() => expect(approvals()).toHaveLength(1))
      expect(JSON.parse(approvals()[0][1].body)).toEqual({ designer_note: '', template_confirm: 'agree', expected_version: 4 })
    })

    it('needs an explanation when the admin says it is not a template Fix', async () => {
      renderModal()
      await screen.findByText('Vneck')

      fireEvent.click(screen.getByRole('button', { name: 'Không đúng, không phải đổi template' }))
      fireEvent.click(screen.getByRole('button', { name: 'Xác Nhận & Giao Des' }))
      expect(await screen.findByText(/giải thích vì sao không phải đổi template/)).toBeTruthy()
      expect(approvals()).toHaveLength(0)

      fireEvent.change(screen.getByRole('textbox', { name: /Giải thích/ }), { target: { value: 'Chỉ đổi màu' } })
      fireEvent.click(screen.getByRole('button', { name: 'Xác Nhận & Giao Des' }))
      await waitFor(() => expect(approvals()).toHaveLength(1))
      expect(JSON.parse(approvals()[0][1].body)).toMatchObject({
        template_confirm: 'disagree', template_confirm_note: 'Chỉ đổi màu',
      })
    })
  })
})
