import { describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch } from './client'
import { createOrderCommandBody, getOrderVersionConflict } from './orderCommand'

describe('order command helpers', () => {
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
