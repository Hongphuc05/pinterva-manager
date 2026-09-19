import { ApiError, apiFetch } from './client'

export type VersionedOrder = {
  id: string
  version: number
}

export type OrderVersionConflict = {
  code: 'ORDER_VERSION_CONFLICT'
  message: string
  order_id: string | null
  expected_version: number | null
  current_version: number | null
  changed_fields: string[]
}

export function createOrderCommandBody<T extends Record<string, unknown>>(
  order: VersionedOrder,
  payload: T,
): T & { expected_version: number; idempotency_key: string } {
  return {
    ...payload,
    expected_version: order.version,
    idempotency_key: crypto.randomUUID(),
  }
}

export function getOrderVersionConflict(error: unknown): OrderVersionConflict | null {
  if (!(error instanceof ApiError) || error.status !== 409 || !error.detail) return null
  const detail = error.detail as Partial<OrderVersionConflict>
  if (detail.code !== 'ORDER_VERSION_CONFLICT') return null
  return {
    code: detail.code,
    message: detail.message || 'Đơn đã được cập nhật bởi người khác.',
    order_id: detail.order_id ?? null,
    expected_version: detail.expected_version ?? null,
    current_version: detail.current_version ?? null,
    changed_fields: detail.changed_fields || [],
  }
}

export async function executeOrderCommand<TResponse, TPayload extends Record<string, unknown>>(
  path: string,
  method: 'POST' | 'PUT' | 'PATCH',
  order: VersionedOrder,
  payload: TPayload,
): Promise<TResponse> {
  return apiFetch<TResponse>(path, {
    method,
    body: JSON.stringify(createOrderCommandBody(order, payload)),
  })
}
