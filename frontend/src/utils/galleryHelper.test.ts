import { describe, expect, it } from 'vitest'

import { deduplicateGalleryUrls } from './galleryHelper'

describe('deduplicateGalleryUrls', () => {
  it('keeps distinct images behind the local asset proxy', () => {
    const proxiedImages = Array.from(
      { length: 9 },
      (_, index) => `/api/assets/proxy?u=encoded-image-${index + 1}`,
    )

    expect(deduplicateGalleryUrls([...proxiedImages, proxiedImages[0]])).toEqual(proxiedImages)
  })
})
