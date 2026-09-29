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

export const fetchPendingDesigners = () => apiFetch<PendingDesigner[]>('/accountant/designers')

export const fetchPendingDesignerDetail = (designerId: string) =>
  apiFetch<PendingDesignerDetail>(`/accountant/designers/${designerId}`)

export const payDesigner = (designerId: string, orderIds: string[], expectedTotal: number) =>
  apiFetch<{ ok: boolean; paid_count: number; total_amount: number }>(`/accountant/designers/${designerId}/pay`, {
    method: 'POST',
    body: JSON.stringify({ order_ids: orderIds, expected_total: expectedTotal }),
  })

export const fetchPaymentHistory = (page = 1) =>
  apiFetch<PaymentHistoryResponse>(`/finance/payment-history?page=${page}&page_size=50`)
