import { useEffect } from 'react'
import { apiFetch } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../context/ToastContext'

interface PrintervalAlert {
  id: string
  created_at: string
  order_code: string | null
  action: string | null
  error: string | null
  manual: string | null
}

const POLL_MS = 30_000
const MAX_TOASTS_PER_POLL = 5

const sinceKey = (userId: string) => `printervalAlerts.since.${userId}`

function readSince(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeSince(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // storage blocked: the next load starts from the last 24 hours again
  }
}

/** Admin only: a toast for every write to Printerval that failed, with what to do by hand. */
export function PrintervalAlertToasts() {
  const { user } = useAuth()
  const { showToast } = useToast()
  const isAdmin = user?.role === 'admin'
  const userId = user?.id

  useEffect(() => {
    if (!isAdmin || !userId) return
    const key = sinceKey(userId)
    let alive = true
    const poll = async () => {
      const since = readSince(key) // shared by every tab, so one alert is not shown twice
      try {
        const query = since ? `?since=${encodeURIComponent(since)}` : ''
        const { items, now } = await apiFetch<{ items: PrintervalAlert[]; now: string }>(`/printerval-alerts${query}`)
        if (!alive) return
        const shown = items.slice(-MAX_TOASTS_PER_POLL)
        for (const alert of shown) {
          showToast(
            `Không cập nhật được Printerval · ${alert.order_code ?? '?'}: ${alert.action ?? ''}. ` +
              `Lỗi: ${alert.error ?? 'không rõ'}. Cần làm tay: ${alert.manual ?? ''}`,
            'error',
            20_000,
          )
        }
        if (items.length > shown.length) {
          showToast(`Còn ${items.length - shown.length} lỗi cập nhật Printerval khác chưa hiện.`, 'error', 20_000)
        }
        writeSince(key, items.length ? items[items.length - 1].created_at : (since ?? now))
      } catch {
        // transient: the next poll retries
      }
    }
    void poll()
    const timer = setInterval(() => void poll(), POLL_MS)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [isAdmin, userId, showToast])

  return null
}
