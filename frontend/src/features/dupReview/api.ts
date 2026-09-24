import { apiFetch } from '../../api/client'
import type { Item, Job, QueueState, SearchResult, WorkerDevice } from './types'

const BASE = '/support-review'
const WORKER = '/support-worker'

export const fetchJobs = () => apiFetch<{ jobs: Job[] }>(`${BASE}/jobs`).then((r) => r.jobs)

export const fetchJob = (id: string) => apiFetch<{ job: Job; items: Item[] }>(`${BASE}/jobs/${id}`)

export const selectCandidate = (itemId: string, candidateId: string) =>
  apiFetch(`${BASE}/items/${itemId}/select`, { method: 'POST', body: JSON.stringify({ candidate_id: candidateId }) })

export const rejectItem = (itemId: string) => apiFetch(`${BASE}/items/${itemId}/reject`, { method: 'POST' })

export const cancelJob = (jobId: string) => apiFetch(`${BASE}/jobs/${jobId}/cancel`, { method: 'POST' })

export const fetchQueue = () => apiFetch<QueueState>(`${BASE}/queue`)

export type SearchStage = 'queued' | 'running'

interface SearchStatus {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  result: SearchResult | null
  error: string | null
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * A search is queued for a Support machine (only it holds the model): submit the picture, then poll
 * until a machine has answered. `onStage` reports whether it is still waiting for a machine.
 */
export async function searchByImage(
  file: File,
  onStage?: (stage: SearchStage) => void,
  opts: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<SearchResult> {
  const form = new FormData()
  form.append('file', file)
  const { id } = await apiFetch<{ id: string }>(`${BASE}/search?top_k=10`, { method: 'POST', body: form })
  const interval = opts.intervalMs ?? 2000
  const deadline = Date.now() + (opts.timeoutMs ?? 15 * 60_000)
  for (;;) {
    const status = await apiFetch<SearchStatus>(`${BASE}/search/${id}`)
    if (status.status === 'completed' && status.result) return status.result
    if (status.status === 'failed') throw new Error(status.error || 'Máy Support không tìm được ảnh này')
    onStage?.(status.status === 'running' ? 'running' : 'queued')
    if (Date.now() > deadline) throw new Error('Quá thời gian chờ: chưa có máy Support nào xử lý. Kiểm tra trang Hàng đợi.')
    await sleep(interval)
  }
}

export const lookupDevice = (userCode: string) =>
  apiFetch<{ machine_name: string; user_code: string }>(`${WORKER}/devices/lookup`, {
    method: 'POST',
    body: JSON.stringify({ user_code: userCode }),
  })

export const approveDevice = (userCode: string) =>
  apiFetch<WorkerDevice>(`${WORKER}/devices/approve`, { method: 'POST', body: JSON.stringify({ user_code: userCode }) })

export const revokeDevice = (id: string) => apiFetch(`${WORKER}/devices/${id}/revoke`, { method: 'POST' })

export const sendPresence = () => apiFetch<{ devices: WorkerDevice[] }>(`${WORKER}/presence`, { method: 'POST' })
