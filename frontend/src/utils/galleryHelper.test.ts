import { describe, expect, it } from 'vitest'

import { deduplicateGalleryUrls } from './galleryHelper'

describe('deduplicateGalleryUrls', () => {
  it('repairs a legacy eBay URL incorrectly prefixed by the source CDN', () => {
    expect(deduplicateGalleryUrls([
      'https://assets.printerval.com/i.ebayimg.com/images/g/iVMAAOSwsO9mKHs-/s-l1600.webp',
    ])).toEqual([
      'https://i.ebayimg.com/images/g/iVMAAOSwsO9mKHs-/s-l1600.webp',
    ])
  })

  it('keeps distinct images behind the local asset proxy', () => {
    const proxiedImages = Array.from(
      { length: 9 },
      (_, index) => `/api/assets/proxy?u=encoded-image-${index + 1}`,
    )

    expect(deduplicateGalleryUrls([...proxiedImages, proxiedImages[0]])).toEqual(proxiedImages)
  })
})
