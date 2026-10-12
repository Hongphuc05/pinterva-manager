import { apiFetch } from '../../api/client'

export interface CompareStatus {
  enabled: boolean
  /** Orders a /check would queue now. */
  new_orders: number
  /** Compared orders with no duplicate that /handle would move to Không trùng lặp. */
  handleable_orders: number
}

export const fetchCompareStatus = () => apiFetch<CompareStatus>('/support-compare/status')

/** Same as Telegram /check → Có: one job with the orders that were never compared. */
export const startCheck = () =>
  apiFetch<{ job_id: string; requested_count: number }>('/support-compare/check', { method: 'POST' })

/** Same as Telegram /handle → Có. */
export const startHandle = () => apiFetch<{ handled_count: number }>('/support-compare/handle', { method: 'POST' })
