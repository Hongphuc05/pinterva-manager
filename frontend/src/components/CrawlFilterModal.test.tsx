import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CrawlFilterModal } from './CrawlFilterModal'

describe('CrawlFilterModal', () => {
  it('submits the explicit unassigned-designer filter', () => {
    const onSearch = vi.fn()
    render(
      <CrawlFilterModal
        isOpen
        onClose={vi.fn()}
        onSearch={onSearch}
        loading={false}
        designers={['Designer A']}
      />,
    )

    fireEvent.change(screen.getByLabelText('Designer'), { target: { value: '__unassigned__' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(onSearch).toHaveBeenCalledWith('Tất cả 2D & 3D', 'Waiting', '__unassigned__', '', '')
  })

  it('submits Printerval Choose Designer as its own filter', () => {
    const onSearch = vi.fn()
    render(
      <CrawlFilterModal
        isOpen
        onClose={vi.fn()}
        onSearch={onSearch}
        loading={false}
        designers={[]}
      />,
    )

    fireEvent.change(screen.getByLabelText('Designer'), { target: { value: '__choose_designer__' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(onSearch).toHaveBeenCalledWith('Tất cả 2D & 3D', 'Waiting', '__choose_designer__', '', '')
  })
})
