import { apiFetch } from '../../api/client'

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

/** `week` is any day of the wanted Monday–Sunday week (YYYY-MM-DD); omitted means every week. */
const weekQuery = (week?: string | null) => (week ? `?week=${encodeURIComponent(week)}` : '')

export const fetchPendingDesigners = (week?: string | null) =>
  apiFetch<PendingDesigner[]>(`/accountant/designers${weekQuery(week)}`)

export const fetchPendingDesignerDetail = (designerId: string, week?: string | null) =>
  apiFetch<PendingDesignerDetail>(`/accountant/designers/${designerId}${weekQuery(week)}`)

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
