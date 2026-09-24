import { apiFetch } from '../../api/client'

export interface QueueJob {
  id: string
  status: 'queued' | 'running' | string
  requested_count: number
  /** Orders of this job that still have to be checked. */
  remaining_count: number
  requested_by: string | null
  created_at: string | null
  started_at: string | null
  worker_name: string | null
}

export interface QueueOverview {
  waiting_jobs: number
  jobs: QueueJob[]
  machines: { ready: number; paused: number; offline: number }
}

export interface JobOrders {
  id: string
  status: string
  requested_count: number
  orders: { order_id: string; external_order_id: string; product_name: string | null; thumbnail_url: string | null }[]
}

export const fetchQueue = () => apiFetch<QueueOverview>('/support-worker/queue')
export const fetchJobOrders = (jobId: string) => apiFetch<JobOrders>(`/support-worker/queue/jobs/${jobId}/orders`)
