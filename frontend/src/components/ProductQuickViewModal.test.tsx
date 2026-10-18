import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProductQuickViewModal } from './ProductQuickViewModal'

vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 's1', role: 'support', username: 'sp', full_name: 'Support' } }) }))

describe('ProductQuickViewModal', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          order: {
            id: 'order-1',
            product_name: 'Áo test',
            product_category: 'Shirt',
            product_variants: [
              { name: 'Type', value: 'Unisex' },
              { name: 'Size', value: 'M' },
            ],
            product_skus: [
              { variants: [{ name: 'Style', value: 'Rundhalsausschnitt Shirt' }] },
            ],
            custom_config: null,
            source_files: null,
            product_image_urls: [],
            thumbnail_url: null,
          },
        }),
      })),
    )
  })

  it('renders Style sourced from SKU variants', async () => {
    render(<ProductQuickViewModal orderId="order-1" onClose={vi.fn()} />)

    await waitFor(() => expect(screen.getByText('Style')).toBeInTheDocument())
    expect(screen.getByText('Rundhalsausschnitt Shirt')).toBeInTheDocument()
  })

  it('shows the order work notes only when asked (Support)', async () => {
    const { unmount } = render(<ProductQuickViewModal orderId="order-1" onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('Style')).toBeInTheDocument())
    expect(screen.queryByText('Note làm việc')).not.toBeInTheDocument()
    unmount()

    render(<ProductQuickViewModal orderId="order-1" onClose={vi.fn()} showWorkNotes />)
    await waitFor(() => expect(screen.getByText('Note làm việc')).toBeInTheDocument())
  })
})
