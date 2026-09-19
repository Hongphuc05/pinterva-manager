import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ProductGalleryCard } from './ProductGalleryCard'

describe('ProductGalleryCard', () => {
  it('hides an image that fails to load without removing the remaining gallery', () => {
    render(
      <ProductGalleryCard
        images={['https://images.example/one.jpg', 'https://images.example/two.jpg']}
        onSelectImage={vi.fn()}
      />,
    )

    fireEvent.error(screen.getByAltText('Product view 2'))
    expect(screen.getByAltText('Product view 2')).toBeInTheDocument()
    fireEvent.error(screen.getByAltText('Product view 2'))

    expect(screen.getByAltText('Product view 1')).toBeInTheDocument()
    expect(screen.queryByAltText('Product view 2')).not.toBeInTheDocument()
    expect(screen.getByText(/Đã ẩn một ảnh không thể tải/)).toBeInTheDocument()
    expect(screen.getByText('1 ảnh')).toBeInTheDocument()
  })
})
