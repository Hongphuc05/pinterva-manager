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

/** A machine running the compute agent for the whole team, as every Support account sees it. */
export interface QueueHost {
  id: string
  machine_name: string
  /** The Support account whose login allows this machine. */
  owner: string | null
  state: 'idle' | 'busy' | 'paused' | 'offline' | string
  device: string | null
  progress: {
    phase?: 'idle' | 'syncing_pool' | 'comparing'
    pool_loaded?: number
    pool_total?: number
    job_total?: number
    job_embedded?: number
    job_compared?: number
  }
  last_seen_at: string | null
  expires_at: string
}

export interface QueueOverview {
  waiting_jobs: number
  jobs: QueueJob[]
  hosts?: QueueHost[]
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
