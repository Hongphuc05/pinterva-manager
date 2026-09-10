import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../api/client'

export type SyncStatus = {
  is_running: boolean
  last_started_at: string | null
  last_finished_at: string | null
  last_result: Record<string, unknown> | null
  last_error: string | null
}

type SyncJob = {
  id: string
  type: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  total: number
  processed: number
  updated: number
  failed: number
  message: string | null
  error_summary: string | null
  started_at: string | null
  finished_at: string | null
}

type SyncSnapshot = { status: SyncStatus | null; isTriggering: boolean }

const IDLE_POLL_MS = 15_000
const RUNNING_POLL_MS = 3_000
const listeners = new Set<(snapshot: SyncSnapshot) => void>()
let snapshot: SyncSnapshot = { status: null, isTriggering: false }
let pollTimer: ReturnType<typeof setTimeout> | null = null
let pollInFlight: Promise<void> | null = null

function toSyncStatus(job: SyncJob | null): SyncStatus {
  return {
    is_running: job?.status === 'queued' || job?.status === 'running',
    last_started_at: job?.started_at ?? null,
    last_finished_at: job?.finished_at ?? null,
    last_result: job
      ? { processed: job.processed, total: job.total, updated: job.updated, failed: job.failed }
      : null,
    last_error: job?.error_summary ?? null,
  }
}

function publish(next: Partial<SyncSnapshot>) {
  snapshot = { ...snapshot, ...next }
  listeners.forEach((listener) => listener(snapshot))
}

function schedulePoll(delay: number) {
  if (pollTimer) clearTimeout(pollTimer)
  if (listeners.size === 0) return
  pollTimer = setTimeout(() => {
    void refreshSyncStatus()
  }, delay)
}

async function refreshSyncStatus() {
  if (pollInFlight) return pollInFlight
  pollInFlight = (async () => {
    try {
      const job = await apiFetch<SyncJob | null>('/sync-jobs/current')
      const status = toSyncStatus(job)
      publish({ status })
      schedulePoll(status.is_running ? RUNNING_POLL_MS : IDLE_POLL_MS)
    } catch {
      schedulePoll(IDLE_POLL_MS)
    } finally {
      pollInFlight = null
    }
  })()
  return pollInFlight
}

async function triggerSyncRun(orderIds?: string[]) {
  publish({ isTriggering: true })
  try {
    const job = await apiFetch<SyncJob>('/sync-jobs', {
      method: 'POST',
      body: JSON.stringify({ type: 'status_sync', ...(orderIds?.length ? { order_ids: orderIds } : {}) }),
    })
    publish({ status: toSyncStatus(job) })
    schedulePoll(RUNNING_POLL_MS)
  } finally {
    publish({ isTriggering: false })
  }
}

/** A platform-wide external store. Topbar and the active Orders view subscribe to
 * the same poller, so one visible page produces one `/sync-jobs/current` request. */
export function useSyncStatus() {
  const [current, setCurrent] = useState<SyncSnapshot>(snapshot)

  useEffect(() => {
    listeners.add(setCurrent)
    void refreshSyncStatus()
    return () => {
      listeners.delete(setCurrent)
      if (listeners.size === 0 && pollTimer) {
        clearTimeout(pollTimer)
        pollTimer = null
      }
    }
  }, [])

  const triggerRun = useCallback((orderIds?: string[]) => triggerSyncRun(orderIds), [])
  return { status: current.status, triggerRun, isTriggering: current.isTriggering }
}
