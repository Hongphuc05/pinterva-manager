import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('../api/client', () => api)

import { FixTemplateConfirmCard } from './FixTemplateConfirmCard'

const request = { round: 1, url: 'https://drive.test/temp', note: 'Đổi sang temp Vneck', requested_at: '2026-10-20T01:00:00Z' }

describe('FixTemplateConfirmCard', () => {
  beforeEach(() => {
    api.apiFetch.mockReset().mockResolvedValue({ ok: true })
    vi.stubGlobal('crypto', { randomUUID: () => 'req-1' })
  })

  it('confirms the template Fix in one click', async () => {
    const onDone = vi.fn()
    render(<FixTemplateConfirmCard orderId="o1" request={request} onDone={onDone} />)
    expect(screen.getByText(/Đổi sang temp Vneck/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận Fix do đổi template' }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    const [path, init] = api.apiFetch.mock.calls[0]
    expect(path).toBe('/orders/o1/printerval-template-confirm')
    expect(JSON.parse(init.body)).toEqual({ decision: 'agree', request_id: 'req-1' })
  })

  it('a dispute needs a reason before it is sent', async () => {
    render(<FixTemplateConfirmCard orderId="o1" request={request} onDone={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Không đúng, không phải đổi template' }))
    fireEvent.click(screen.getByRole('button', { name: 'Gửi: không phải đổi template' }))
    expect(screen.getByText('Ghi giải thích vì sao không phải đổi template.')).toBeInTheDocument()
    expect(api.apiFetch).not.toHaveBeenCalled()

    fireEvent.change(screen.getByPlaceholderText(/bắt buộc/), { target: { value: 'QC nhầm, temp đúng rồi' } })
    fireEvent.click(screen.getByRole('button', { name: 'Gửi: không phải đổi template' }))
    await waitFor(() => expect(api.apiFetch).toHaveBeenCalled())
    expect(JSON.parse(api.apiFetch.mock.calls[0][1].body)).toEqual({
      decision: 'disagree', note: 'QC nhầm, temp đúng rồi', request_id: 'req-1',
    })
  })
})
