import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ToastProvider, useToast, showAppToast } from './ToastContext'

function TestToastTrigger() {
  const { showToast } = useToast()
  return (
    <div>
      <button onClick={() => showToast('Test success message', 'success')}>Trigger Success</button>
      <button onClick={() => showToast('Test error message', 'error')}>Trigger Error</button>
      <button onClick={() => showAppToast('Test standalone message', 'info')}>Trigger Standalone</button>
    </div>
  )
}

describe('ToastContext', () => {
  it('displays toast on showToast and closes when dismiss is clicked', async () => {
    render(
      <ToastProvider>
        <TestToastTrigger />
      </ToastProvider>
    )

    fireEvent.click(screen.getByText('Trigger Success'))

    await waitFor(() => {
      expect(screen.getByText('Test success message')).toBeInTheDocument()
    })

    const closeBtn = screen.getByTitle('Đóng thông báo')
    fireEvent.click(closeBtn)

    await waitFor(() => {
      expect(screen.queryByText('Test success message')).not.toBeInTheDocument()
    })
  })

  it('displays toast via standalone showAppToast helper', async () => {
    render(
      <ToastProvider>
        <TestToastTrigger />
      </ToastProvider>
    )

    fireEvent.click(screen.getByText('Trigger Standalone'))

    await waitFor(() => {
      expect(screen.getByText('Test standalone message')).toBeInTheDocument()
    })
  })
})
