import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { CopyableOrderCode } from './CopyableOrderCode'

describe('CopyableOrderCode', () => {
  it('renders the order code and copies to clipboard on click without propagating', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    })

    const onRowClick = vi.fn()

    render(
      <div onClick={onRowClick}>
        <CopyableOrderCode code="DJ3974016" />
      </div>
    )

    const button = screen.getByRole('button', { name: /DJ3974016/i })
    expect(button).toBeInTheDocument()

    fireEvent.click(button)

    expect(writeTextMock).toHaveBeenCalledWith('DJ3974016')
    expect(onRowClick).not.toHaveBeenCalled()

    await waitFor(() => {
      expect(screen.getByTitle('Đã sao chép mã đơn!')).toBeInTheDocument()
    })
  })

  it('renders hash prefix when showHash is true', () => {
    render(<CopyableOrderCode code="DJ9999" showHash />)
    expect(screen.getByText('#DJ9999')).toBeInTheDocument()
  })
})
