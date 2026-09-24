import type { Item, Job, SearchResult } from './types'

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail || detail
    } catch {
      /* keep statusText */
    }
    throw new ApiError(detail)
  }
  return res.json() as Promise<T>
}

export const fetchJobs = () => request<{ jobs: Job[] }>('/review/jobs').then((r) => r.jobs)

export const fetchJob = (id: string) => request<{ job: Job; items: Item[] }>(`/review/jobs/${id}`)

export const selectCandidate = (itemId: string, candidateId: string) =>
  request(`/review/items/${itemId}/select`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ candidate_id: candidateId }),
  })

export const rejectItem = (itemId: string) =>
  request(`/review/items/${itemId}/reject`, { method: 'POST' })

export const searchByImage = (file: File, refresh = false) => {
  const form = new FormData()
  form.append('file', file)
  return request<SearchResult>(`/review/search?top_k=10${refresh ? '&refresh=true' : ''}`, { method: 'POST', body: form })
}
