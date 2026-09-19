import { describe, expect, it, vi } from 'vitest'

import { ApiError } from './client'
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
})
