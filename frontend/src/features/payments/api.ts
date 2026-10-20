import { apiFetch, apiFetchBlob } from '../../api/client'

export interface PendingDesigner {
  designer_id: string
  designer_name: string
  username: string | null
  pending_count: number
  pending_amount: number
  has_qr: boolean
}

export interface PendingOrder {
  order_id: string
  external_order_id: string
  product_name: string | null
  thumbnail_url: string | null
  submitted_at: string | null
}

export interface PendingDesignerDetail extends PendingDesigner {
  orders: PendingOrder[]
}

export interface PaymentHistoryItem {
  order_id: string
  external_order_id: string | null
  product_name: string | null
  amount: number | null // null for the Accountant: per-order rate is Admin-only
}

export interface PaymentBatch {
  id: string
  paid_at: string
  paid_by_name: string
  paid_by_role: string | null
  designer_id: string | null
  designer_name: string
  order_count: number
  total_amount: number
  source: 'payment' | 'backfill'
  items: PaymentHistoryItem[]
}

export interface PaymentHistoryResponse {
  batches: PaymentBatch[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

/**
 * Which submitted orders to show: a Monday–Sunday week (any day of it), or a range of whole days (both
 * ends included, either may be empty). All dates are YYYY-MM-DD; null means every order.
 */
export type PaymentPeriod = { week: string } | { from: string; to: string }

export function periodQuery(period?: PaymentPeriod | null): string {
  if (!period) return ''
  const params = new URLSearchParams()
  if ('week' in period) params.set('week', period.week)
  else {
    if (period.from) params.set('date_from', period.from)
    if (period.to) params.set('date_to', period.to)
  }
  const query = params.toString()
  return query ? `?${query}` : ''
}

export const fetchPendingDesigners = (period?: PaymentPeriod | null) =>
  apiFetch<PendingDesigner[]>(`/accountant/designers${periodQuery(period)}`)

// A designer's orders are prefetched when the row is hovered and reused once when it is opened
// (if still fresh), so the popup opens at once instead of waiting ~1-2 s for the server.
const DETAIL_FRESH_MS = 30_000
const detailCache = new Map<string, { at: number; promise: Promise<PendingDesignerDetail> }>()
const detailKey = (designerId: string, period?: PaymentPeriod | null) => `${designerId}|${periodQuery(period)}`

const requestDetail = (designerId: string, period?: PaymentPeriod | null) =>
  apiFetch<PendingDesignerDetail>(`/accountant/designers/${designerId}${periodQuery(period)}`)

export function prefetchPendingDesignerDetail(designerId: string, period?: PaymentPeriod | null) {
  const key = detailKey(designerId, period)
  const cached = detailCache.get(key)
  if (cached && Date.now() - cached.at < DETAIL_FRESH_MS) return
  const promise = requestDetail(designerId, period)
  promise.catch(() => detailCache.delete(key))
  detailCache.set(key, { at: Date.now(), promise })
}

export function fetchPendingDesignerDetail(designerId: string, period?: PaymentPeriod | null) {
  const key = detailKey(designerId, period)
  const cached = detailCache.get(key)
  detailCache.delete(key) // use a prefetch once: a reopened popup always asks the server again
  if (cached && Date.now() - cached.at < DETAIL_FRESH_MS) return cached.promise
  return requestDetail(designerId, period)
}

// Bank QR images rarely change: fetched once per designer for the session and kept as object URLs.
const qrCache = new Map<string, Promise<string[]>>()

export function loadDesignerQr(designerId: string): Promise<string[]> {
  let promise = qrCache.get(designerId)
  if (!promise) {
    promise = apiFetch<{ images: { url: string }[] }>(`/users/${designerId}/bank-qr`).then((res) =>
      Promise.all(res.images.map((img) => apiFetchBlob(img.url).then((blob) => URL.createObjectURL(blob)))),
    )
    promise.catch(() => qrCache.delete(designerId))
    qrCache.set(designerId, promise)
  }
  return promise
}

/** After a payment or a reload: never reuse an order list fetched before it. */
export function clearPendingDetailCache() {
  detailCache.clear()
}

export function clearPaymentCaches() {
  detailCache.clear()
  qrCache.forEach((promise) => promise.then((urls) => urls.forEach((u) => URL.revokeObjectURL(u))).catch(() => {}))
  qrCache.clear()
}

const pad = (n: number) => String(n).padStart(2, '0')
const isoDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const dayMonth = (d: Date) => `${pad(d.getDate())}/${pad(d.getMonth() + 1)}`

/** The last `count` Monday–Sunday weeks, newest first, as options for the week filter. */
export function recentWeeks(count = 8, today = new Date()): { value: string; label: string }[] {
  const monday = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7))
  return Array.from({ length: count }, (_, i) => {
    const start = new Date(monday)
    start.setDate(monday.getDate() - 7 * i)
    const end = new Date(start)
    end.setDate(start.getDate() + 6)
    const name = i === 0 ? 'Tuần này' : i === 1 ? 'Tuần trước' : 'Tuần'
    return { value: isoDate(start), label: `${name} (${dayMonth(start)} – ${dayMonth(end)})` }
  })
}

export const payDesigner = (designerId: string, orderIds: string[], expectedTotal: number) =>
  apiFetch<{ ok: boolean; paid_count: number; total_amount: number }>(`/accountant/designers/${designerId}/pay`, {
    method: 'POST',
    body: JSON.stringify({ order_ids: orderIds, expected_total: expectedTotal }),
  })

export const fetchPaymentHistory = (page = 1) =>
  apiFetch<PaymentHistoryResponse>(`/finance/payment-history?page=${page}&page_size=50`)
