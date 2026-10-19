import { beforeEach, describe, expect, it } from 'vitest'
import {
  MAX_NOTIFICATIONS,
  RETENTION_MS,
  pruneNotifications,
  readNotifications,
  writeNotifications,
  type LoggedNotification,
} from './notificationLog'

const at = (ms: number, id = String(ms)): LoggedNotification => ({ id, message: `m${id}`, type: 'info', at: ms })

describe('notification log', () => {
  beforeEach(() => localStorage.clear())

  it('keeps three days and drops what is older', () => {
    const now = 10 * RETENTION_MS
    const kept = pruneNotifications([at(now - 1000), at(now - RETENTION_MS + 1000), at(now - RETENTION_MS - 1000)], now)
    expect(kept.map((item) => item.at)).toEqual([now - 1000, now - RETENTION_MS + 1000])
  })

  it('keeps at most 200, the newest first', () => {
    const now = Date.now()
    const many = Array.from({ length: MAX_NOTIFICATIONS + 20 }, (_, i) => at(now - i, `n${i}`))
    const kept = pruneNotifications(many, now)
    expect(kept).toHaveLength(MAX_NOTIFICATIONS)
    expect(kept[0].id).toBe('n0')
  })

  it('reads back what was written per user, prunes on read, and survives corrupt storage', () => {
    const now = Date.now()
    writeNotifications('u1', [at(now - 1000, 'new'), at(now - RETENTION_MS - 5000, 'old')])
    expect(readNotifications('u1', now).map((item) => item.id)).toEqual(['new'])
    expect(readNotifications('u2', now)).toEqual([])
    localStorage.setItem('notifications.log.u3', '{not json')
    expect(readNotifications('u3', now)).toEqual([])
  })
})
