import type { ToastType } from './ToastContext'

/** One toast, kept so it can be read again from the bell. */
export type LoggedNotification = { id: string; message: string; type: ToastType; at: number }

export const RETENTION_MS = 3 * 24 * 60 * 60 * 1000
export const MAX_NOTIFICATIONS = 200

const itemsKey = (scope: string) => `notifications.log.${scope}`
const seenKey = (scope: string) => `notifications.seen.${scope}`

/** Newest first; drops what is older than three days and keeps at most MAX_NOTIFICATIONS. */
export function pruneNotifications(items: LoggedNotification[], now = Date.now()): LoggedNotification[] {
  return items.filter((item) => now - item.at < RETENTION_MS).slice(0, MAX_NOTIFICATIONS)
}

export function readNotifications(scope: string, now = Date.now()): LoggedNotification[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(itemsKey(scope)) || '[]')
    if (!Array.isArray(parsed)) return []
    return pruneNotifications(
      parsed.filter((item) => item && typeof item.message === 'string' && typeof item.at === 'number'),
      now,
    )
  } catch {
    return []
  }
}

export function writeNotifications(scope: string, items: LoggedNotification[]) {
  try {
    localStorage.setItem(itemsKey(scope), JSON.stringify(items))
  } catch {
    // storage blocked or full: the bell keeps working for this session only
  }
}

export function readSeenAt(scope: string): number {
  try {
    return Number(localStorage.getItem(seenKey(scope))) || 0
  } catch {
    return 0
  }
}

export function writeSeenAt(scope: string, at: number) {
  try {
    localStorage.setItem(seenKey(scope), String(at))
  } catch {
    // see writeNotifications
  }
}
