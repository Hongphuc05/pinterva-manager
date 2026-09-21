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

function latestTimestamp(...values: Array<string | null | undefined>): string | null {
  return values
    .filter((value): value is string => Boolean(value))
    .sort((left, right) => Date.parse(right) - Date.parse(left))[0] ?? null
}

function toSyncStatus(job: SyncJob | null, platformStatus: SyncStatus | null): SyncStatus {
  const jobIsRunning = job?.status === 'queued' || job?.status === 'running'
  const platformIsRunning = platformStatus?.is_running === true
  const jobStatus: SyncStatus = {
    is_running: jobIsRunning,
    last_started_at: job?.started_at ?? null,
    last_finished_at: job?.finished_at ?? null,
    last_result: job
      ? { processed: job.processed, total: job.total, updated: job.updated, failed: job.failed }
      : null,
    last_error: job?.error_summary ?? null,
  }

  return {
    // Manual tab/header jobs and Celery's scheduled status mirror are durable,
    // independent server-side jobs.  The header must reflect either one after
    // a route change or a full browser reload.
    is_running: jobIsRunning || platformIsRunning,
    last_started_at: latestTimestamp(jobStatus.last_started_at, platformStatus?.last_started_at),
    last_finished_at: latestTimestamp(jobStatus.last_finished_at, platformStatus?.last_finished_at),
    last_result: jobIsRunning || !platformStatus?.last_result
      ? jobStatus.last_result
      : platformStatus.last_result,
    last_error: jobStatus.last_error || platformStatus?.last_error || null,
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
      const [job, platformStatus] = await Promise.all([
        apiFetch<SyncJob | null>('/sync-jobs/current'),
        apiFetch<SyncStatus>('/orders/sync-status'),
      ])
      const status = toSyncStatus(job, platformStatus)
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

async function triggerSyncRun(orderIds?: string[] | null) {
  if (orderIds !== null && orderIds !== undefined && orderIds.length === 0) {
    throw new Error('Không có đơn trong tab hiện tại để đồng bộ.')
  }
  publish({ isTriggering: true })
  try {
    const body: Record<string, unknown> = { type: 'status_sync' }
    if (orderIds && orderIds.length > 0) {
      body.order_ids = orderIds
    }
    const job = await apiFetch<SyncJob>('/sync-jobs', {
      method: 'POST',
      body: JSON.stringify(body),
    })
    publish({ status: toSyncStatus(job, null) })
    schedulePoll(RUNNING_POLL_MS)
  } finally {
    publish({ isTriggering: false })
  }
}

/** A platform-wide external store. Topbar and active pages share one poller for
 * both durable manual SyncJobs and Celery's scheduled PlatformSyncState. */
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

  const triggerRun = useCallback((orderIds?: string[] | null) => triggerSyncRun(orderIds), [])
  return { status: current.status, triggerRun, isTriggering: current.isTriggering }
}
