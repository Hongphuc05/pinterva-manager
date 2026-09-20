import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch, apiFetchBlob, resolveAssetUrl } from './client'
import { createOrderCommandBody, getOrderVersionConflict } from './orderCommand'

describe('order command helpers', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('normalizes an API-suffixed base URL for API requests', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://tacahu.fun/api')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await apiFetch('/orders/order-1')

    expect(fetchMock).toHaveBeenCalledWith(
      'https://tacahu.fun/api/orders/order-1',
      expect.objectContaining({ credentials: 'include' }),
    )
  })

  it('uses the normalized URL when downloading a private attachment', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://tacahu.fun/api/')
    const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob(['image']), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await apiFetchBlob('/orders/order-1/work-notes/note-1/attachments/image-1')

    expect(fetchMock).toHaveBeenCalledWith(
      'https://tacahu.fun/api/orders/order-1/work-notes/note-1/attachments/image-1',
      expect.objectContaining({ credentials: 'include' }),
    )
    expect(resolveAssetUrl('/api/orders/order-1/asset')).toBe('https://tacahu.fun/api/orders/order-1/asset')
  })

  it('adds the current revision and a fresh idempotency key', () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'command-key' })

    expect(createOrderCommandBody({ id: 'order-1', version: 7 }, { state: 'IN_PROGRESS' })).toEqual({
      state: 'IN_PROGRESS',
      expected_version: 7,
      idempotency_key: 'command-key',
    })
  })

  it('recognizes the shared 409 response contract', () => {
    const error = new ApiError(409, 'conflict', {
      code: 'ORDER_VERSION_CONFLICT',
      message: 'Đơn đã thay đổi',
      order_id: 'order-1',
      expected_version: 7,
      current_version: 8,
      changed_fields: ['state'],
    })

    expect(getOrderVersionConflict(error)).toMatchObject({
      order_id: 'order-1',
      current_version: 8,
      changed_fields: ['state'],
    })
  })

  it('publishes one refresh signal for a version conflict', async () => {
    const onConflict = vi.fn()
    const onRefresh = vi.fn()
    const onToast = vi.fn()
    window.addEventListener('order-version-conflict', onConflict)
    window.addEventListener('orders-updated', onRefresh)
    window.addEventListener('app-toast', onToast)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: {
        code: 'ORDER_VERSION_CONFLICT',
        message: 'Đơn đã thay đổi',
        order_id: 'order-1',
      },
    }), { status: 409, statusText: 'Conflict', headers: { 'Content-Type': 'application/json' } })))

    await expect(apiFetch('/orders/order-1/state')).rejects.toMatchObject({ status: 409 })

    expect(onConflict).toHaveBeenCalledTimes(1)
    expect(onRefresh).toHaveBeenCalledTimes(1)
    expect(onToast).toHaveBeenCalledTimes(1)
    window.removeEventListener('order-version-conflict', onConflict)
    window.removeEventListener('orders-updated', onRefresh)
    window.removeEventListener('app-toast', onToast)
  })
})
