import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from '../api/client'

export type SyncStatus = {
  is_running: boolean
  last_started_at: string | null
  last_finished_at: string | null
  last_result: Record<string, unknown> | null
  last_error: string | null
}

const IDLE_POLL_MS = 15000
const RUNNING_POLL_MS = 3000

/** Polls GET /orders/sync-status for the current platform's read-only status-mirror
 * job — polls faster while it's running so the UI's spin indicator catches the
 * moment it stops. Shared by Topbar (icon) and OrderStatusPage (table + button). */
export function useSyncStatus() {
  const [status, setStatus] = useState<SyncStatus | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  const poll = useCallback(async () => {
    try {
      const res = await apiFetch<SyncStatus>('/orders/sync-status')
      if (!mountedRef.current) return
      setStatus(res)
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(poll, res.is_running ? RUNNING_POLL_MS : IDLE_POLL_MS)
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
    const res = await apiFetch<SyncStatus>('/orders/sync-status/run', { method: 'POST' })
    setStatus(res)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(poll, RUNNING_POLL_MS)
  }, [poll])

  return { status, triggerRun }
}
