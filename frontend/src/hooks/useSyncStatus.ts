import { useCallback, useEffect, useRef, useState } from 'react'
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

function toSyncStatus(job: SyncJob | null): SyncStatus {
  return {
    is_running: job?.status === 'queued' || job?.status === 'running',
    last_started_at: job?.started_at ?? null,
    last_finished_at: job?.finished_at ?? null,
    last_result: job ? { processed: job.processed, total: job.total, updated: job.updated, failed: job.failed } : null,
    last_error: job?.error_summary ?? null,
  }
}

const IDLE_POLL_MS = 15000
const RUNNING_POLL_MS = 3000

/** Polls GET /orders/sync-status for the current platform's read-only status-mirror
 * job — polls faster while it's running so the UI's spin indicator catches the
 * moment it stops. Shared by Topbar (icon) and OrderStatusPage (table + button). */
export function useSyncStatus() {
  const [status, setStatus] = useState<SyncStatus | null>(null)
  const [isTriggering, setIsTriggering] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  const poll = useCallback(async () => {
    try {
      const res = await apiFetch<SyncJob | null>('/sync-jobs/current')
      if (!mountedRef.current) return
      const next = toSyncStatus(res)
      setStatus(next)
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(poll, next.is_running ? RUNNING_POLL_MS : IDLE_POLL_MS)
    } catch {
      if (!mountedRef.current) return
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(poll, IDLE_POLL_MS)
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    poll()
    return () => {
      mountedRef.current = false
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [poll])

  const triggerRun = useCallback(async () => {
    setIsTriggering(true)
    try {
      const res = await apiFetch<SyncJob>('/sync-jobs', {
        method: 'POST',
        body: JSON.stringify({ type: 'status_sync' }),
      })
      setStatus(toSyncStatus(res))
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(poll, RUNNING_POLL_MS)
    } catch (err) {
      console.error('Failed to trigger sync:', err)
      throw err
    } finally {
      setIsTriggering(false)
    }
  }, [poll])

  return { status, triggerRun, isTriggering }
}
