import { useEffect } from 'react'
import { apiFetch } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../context/ToastContext'

interface UnreadChat {
  order_id: string
  order_code: string
  count: number
}

const POLL_MS = 30_000
const MAX_TOASTS_PER_POLL = 5

const storageKey = (userId: string) => `printervalChat.toasted.${userId}`

function readSeen(key: string): Record<string, number> {
  try {
    return JSON.parse(localStorage.getItem(key) || '{}')
  } catch {
    return {}
  }
}

function writeSeen(key: string, value: Record<string, number>) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // storage blocked: the next poll toasts what is still unread again
  }
}

/**
 * Admin only: a toast naming each order that has a new message in Printerval's chat. The unread list
 * is Printerval's own, so an order disappears from it once somebody reads it and toasts again on the next
 * message. Only a visible tab takes the toast, like the write-failure alerts.
 */
export function PrintervalChatToasts() {
  const { user } = useAuth()
  const { showToast } = useToast()
  const isAdmin = user?.role === 'admin'
  const userId = user?.id

  useEffect(() => {
    if (!isAdmin || !userId) return
    const key = storageKey(userId)
    let alive = true
    const poll = async () => {
      if (document.visibilityState !== 'visible') return
      try {
        const { items, stale } = await apiFetch<{ items: UnreadChat[]; stale: boolean }>('/printerval-chat/unread')
        if (!alive || stale) return
        const seen = readSeen(key) // shared by every tab, so one message is not toasted twice
        const fresh = items.filter((item) => item.count > (seen[item.order_code] ?? 0))
        for (const item of fresh.slice(0, MAX_TOASTS_PER_POLL)) {
          showToast(`${item.order_code} có tin nhắn mới trên chat Printerval`, 'info', 15_000)
        }
        if (fresh.length > MAX_TOASTS_PER_POLL) {
          showToast(`Còn ${fresh.length - MAX_TOASTS_PER_POLL} đơn khác có tin nhắn mới trên chat Printerval.`, 'info', 15_000)
        }
        // Keep only orders still unread, so a later message on a read order toasts again.
        writeSeen(key, Object.fromEntries(items.map((item) => [item.order_code, item.count])))
      } catch {
        // transient: the next poll retries
      }
    }
    void poll()
    const timer = setInterval(() => void poll(), POLL_MS)
    const onVisible = () => void poll()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      alive = false
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [isAdmin, userId, showToast])

  return null
}
