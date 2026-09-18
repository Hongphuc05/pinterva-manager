import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { CopyableProductName } from './CopyableProductName'

describe('CopyableProductName', () => {
  it('renders product name and copies to clipboard on click without propagating', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    })

    const onRowClick = vi.fn()

    render(
      <div onClick={onRowClick}>
        <CopyableProductName name="Dallas Vintage Cotton T-Shirt" />
      </div>
    )

    const button = screen.getByRole('button', { name: /Dallas Vintage Cotton T-Shirt/i })
    expect(button).toBeInTheDocument()

    fireEvent.click(button)

    expect(writeTextMock).toHaveBeenCalledWith('Dallas Vintage Cotton T-Shirt')
    expect(onRowClick).not.toHaveBeenCalled()

    await waitFor(() => {
      expect(screen.getByTitle('Đã sao chép tên sản phẩm!')).toBeInTheDocument()
    })
  })
})
