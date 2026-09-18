import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { GallerySyncProvider, useGallerySync, type PendingGalleryOrder } from './GallerySyncContext'
import React from 'react'

const mockAuth = {
  user: { id: 'admin-1', role: 'admin', full_name: 'Admin' },
  logout: vi.fn(),
}

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => mockAuth,
}))

vi.mock('../auth/PlatformContext', () => ({
  usePlatform: () => ({ activePlatform: { id: 'plat-1' } }),
}))

describe('GallerySyncContext', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('prioritizes order to index 0 and processes the single order', async () => {
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <GallerySyncProvider>{children}</GallerySyncProvider>
    )

    const orderA: PendingGalleryOrder = {
      id: 'ord-1',
      external_order_id: 'DJ1001',
      product_name: 'T-Shirt A',
      thumbnail_url: 'https://thumb.a',
      sales_url: 'https://mock-shop.com/a',
      image_count: 1,
    }

    const orderB: PendingGalleryOrder = {
      id: 'ord-2',
      external_order_id: 'DJ1002',
      product_name: 'T-Shirt B',
      thumbnail_url: 'https://thumb.b',
      sales_url: 'https://mock-shop.com/b',
      image_count: 1,
    }

    // Stub global fetch
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/orders/pending-galleries')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ orders: [orderA, orderB] }),
          })
        }
        if (url.includes('/sync-gallery')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ ok: true, image_count: 3 }),
          })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
      })
    )

    const { result } = renderHook(() => useGallerySync(), { wrapper })

    // Prioritize order B
    await act(async () => {
      await result.current.prioritizeOrder(orderB)
    })

    expect(result.current.syncStatusMap['ord-2']?.status).toBe('success')
    expect(result.current.syncStatusMap['ord-2']?.count).toBe(3)
  })

  it('supports pause and resume', async () => {
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <GallerySyncProvider>{children}</GallerySyncProvider>
    )

    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve({ ok: true, status: 200, json: async () => ({ orders: [] }) }))
    )

    const { result } = renderHook(() => useGallerySync(), { wrapper })

    expect(result.current.isPaused).toBe(false)

    await act(async () => {
      result.current.pauseSync()
    })
    expect(result.current.isPaused).toBe(true)
    expect(localStorage.getItem('tacahu_gallery_sync_paused')).toBe('true')

    await act(async () => {
      result.current.resumeSync()
    })
    expect(result.current.isPaused).toBe(false)
    expect(localStorage.getItem('tacahu_gallery_sync_paused')).toBe('false')
  })
})
