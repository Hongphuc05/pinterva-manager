import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FixDisputeBadge, FixDisputeModal, type FixDisputeRecord } from './FixDispute'

const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  apiFetch: api.apiFetch,
}))

const NOTE = 'Đơn dạng 3D, vẫn làm theo temp đang làm'

function openModal() {
  const onSent = vi.fn()
  const onClose = vi.fn()
  render(<FixDisputeModal orderId="o1" orderVersion={4} externalOrderId="DJ4107184" onClose={onClose} onSent={onSent} />)
  return { onSent, onClose }
}

describe('FixDisputeModal', () => {
  it('has the same two fields as Printerval and sends them with the order version', async () => {
    api.apiFetch.mockReset().mockResolvedValue({ ok: true })
    const { onSent, onClose } = openModal()
    expect(screen.getByText('DJ4107184 — Báo FIX không đúng')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/Vì sao FIX không đúng/), { target: { value: NOTE } })
    fireEvent.change(screen.getByLabelText(/Link ảnh chứng minh/), { target: { value: 'https://img.test/1.png\n\n https://img.test/2.png ' } })
    fireEvent.click(screen.getByText('Gửi khiếu nại'))

    await waitFor(() => expect(onSent).toHaveBeenCalled())
    expect(onClose).toHaveBeenCalled()
    const [path, init] = api.apiFetch.mock.calls[0]
    expect(path).toBe('/orders/o1/fix-dispute')
    expect(JSON.parse(init.body)).toEqual({ note: NOTE, images: ['https://img.test/1.png', 'https://img.test/2.png'], expected_version: 4 })
  })

  it('applies Printerval checks before sending', () => {
    api.apiFetch.mockReset()
    openModal()
    fireEvent.change(screen.getByLabelText(/Vì sao FIX không đúng/), { target: { value: 'ngắn' } })
    fireEvent.click(screen.getByText('Gửi khiếu nại'))
    expect(screen.getByText(/ít nhất 10 ký tự/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/Vì sao FIX không đúng/), { target: { value: NOTE } })
    fireEvent.change(screen.getByLabelText(/Link ảnh chứng minh/), { target: { value: 'img.test/1.png' } })
    fireEvent.click(screen.getByText('Gửi khiếu nại'))
    expect(screen.getByText(/bắt đầu bằng http/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/Link ảnh chứng minh/), { target: { value: [1, 2, 3, 4, 5, 6].map((i) => `https://a/${i}`).join('\n') } })
    fireEvent.click(screen.getByText('Gửi khiếu nại'))
    expect(screen.getByText('Tối đa 5 link ảnh.')).toBeInTheDocument()
    expect(api.apiFetch).not.toHaveBeenCalled()
  })
})

describe('FixDisputeBadge', () => {
  const base: FixDisputeRecord = { round: 1, note: NOTE, images: [], push: 'sent', remote_status: 'pending', outcome: null }

  it('shows where the dispute stands', () => {
    const { rerender } = render(<FixDisputeBadge dispute={base} orderId="o1" />)
    expect(screen.getByText('Đang chờ phân xử khiếu nại')).toBeInTheDocument()
    rerender(<FixDisputeBadge dispute={{ ...base, remote_status: 'rejected', outcome: 'rejected', arbiter_note: 'sai màu' }} orderId="o1" />)
    expect(screen.getByText(/Khiếu nại bị bác — FIX đúng: sai màu/)).toBeInTheDocument()
    rerender(<FixDisputeBadge dispute={{ ...base, outcome: 'accepted' }} orderId="o1" />)
    expect(screen.getByText(/được chấp nhận/)).toBeInTheDocument()
  })

  it('lets the Admin send a failed dispute again', async () => {
    api.apiFetch.mockReset().mockResolvedValue({ ok: true })
    const onRetried = vi.fn()
    render(<FixDisputeBadge dispute={{ ...base, push: 'failed', push_error: 'HTTP 422' }} orderId="o1" orderVersion={7} onRetried={onRetried} />)
    expect(screen.getByText(/Gửi khiếu nại lỗi: HTTP 422/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('Gửi lại'))
    await waitFor(() => expect(onRetried).toHaveBeenCalled())
    expect(api.apiFetch).toHaveBeenCalledWith('/orders/o1/fix-dispute/retry', { method: 'POST', body: JSON.stringify({ expected_version: 7 }) })
  })
})
