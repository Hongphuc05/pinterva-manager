import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { ToastProvider, useToast } from '../context/ToastContext'
import { NotificationBell } from './NotificationBell'

function Harness({ scope }: { scope: string | null }) {
  return (
    <ToastProvider scope={scope}>
      <Raise />
      <NotificationBell />
    </ToastProvider>
  )
}

function Raise() {
  const { showToast } = useToast()
  return (
    <>
      <button onClick={() => showToast('Không cập nhật được Printerval · DJ1', 'error')}>raise-error</button>
      <button onClick={() => showToast('Đã lưu', 'success')}>raise-ok</button>
    </>
  )
}

describe('NotificationBell', () => {
  beforeEach(() => localStorage.clear())

  it('keeps every toast, counts the unseen ones and clears the count once opened', () => {
    render(<Harness scope="u1" />)
    expect(screen.getByRole('button', { name: 'Thông báo' })).toBeInTheDocument()

    fireEvent.click(screen.getByText('raise-error'))
    fireEvent.click(screen.getByText('raise-ok'))
    expect(screen.getByRole('button', { name: 'Thông báo, 2 chưa xem' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Thông báo/ }))
    const panel = screen.getByRole('dialog', { name: 'Thông báo' })
    expect(panel).toHaveTextContent('Không cập nhật được Printerval · DJ1')
    expect(panel).toHaveTextContent('Đã lưu')
    expect(screen.getByRole('button', { name: 'Thông báo' })).toBeInTheDocument() // no unseen count any more
  })

  it('shows the history again after a reload, only to the same user, and can be cleared', () => {
    const first = render(<Harness scope="u1" />)
    fireEvent.click(screen.getByText('raise-error'))
    first.unmount()

    const again = render(<Harness scope="u1" />)
    fireEvent.click(screen.getByRole('button', { name: /Thông báo/ }))
    expect(screen.getByRole('dialog')).toHaveTextContent('DJ1')
    fireEvent.click(screen.getByRole('button', { name: /Xóa tất cả/ }))
    expect(screen.getByText('Chưa có thông báo nào trong 3 ngày qua.')).toBeInTheDocument()
    again.unmount()

    render(<Harness scope="u2" />)
    fireEvent.click(screen.getByRole('button', { name: /Thông báo/ }))
    expect(screen.getByText('Chưa có thông báo nào trong 3 ngày qua.')).toBeInTheDocument()
  })
})
