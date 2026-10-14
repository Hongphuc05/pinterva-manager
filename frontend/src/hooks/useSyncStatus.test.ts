import { describe, expect, it } from 'vitest'
import { toSyncStatus } from './useSyncStatus'

type Job = NonNullable<Parameters<typeof toSyncStatus>[0]>
type Platform = NonNullable<Parameters<typeof toSyncStatus>[1]>

const job = (finished_at: string, error_summary: string | null): Job => ({
  id: 'j', type: 'status_sync', status: error_summary ? 'failed' : 'succeeded',
  total: 1, processed: 1, updated: 0, failed: 0, message: null, error_summary,
  started_at: finished_at, finished_at, worker_task_id: null, last_heartbeat_at: null,
  progress_phase: null, current_order_code: null,
})

const platform = (last_finished_at: string, last_error: string | null): Platform => ({
  is_running: false, last_started_at: last_finished_at, last_finished_at, worker_task_id: null,
  last_heartbeat_at: null, progress: null, last_result: null, last_error,
})

describe('toSyncStatus last_error', () => {
  it('a manual job that succeeded after a failed scheduled run clears the badge', () => {
    const status = toSyncStatus(job('2026-10-14T08:10:00Z', null), platform('2026-10-14T08:07:00Z', 'heartbeat lost'))
    expect(status.last_error).toBeNull()
  })

  it('a scheduled run that failed after a successful manual job shows its error', () => {
    const status = toSyncStatus(job('2026-10-14T08:00:00Z', null), platform('2026-10-14T08:07:00Z', 'heartbeat lost'))
    expect(status.last_error).toBe('heartbeat lost')
  })

  it('shows the scheduled error when there is no manual job', () => {
    expect(toSyncStatus(null, platform('2026-10-14T08:07:00Z', 'heartbeat lost')).last_error).toBe('heartbeat lost')
  })
})
