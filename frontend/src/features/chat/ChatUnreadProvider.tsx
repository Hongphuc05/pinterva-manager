import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { apiFetch } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../context/ToastContext'

export interface ChatUnreadItem {
  order_id: string
  order_code: string
  count: number
  latest_id: number
  sender_name: string
  snippet: string
}

interface ChatUnreadValue {
  /** Orders with Printerval chat messages the signed-in user has not read, by order id. */
  unread: Record<string, ChatUnreadItem>
  refresh: () => Promise<void>
}

const POLL_MS = 30_000
const CHAT_ROLES = ['admin']
const Context = createContext<ChatUnreadValue>({ unread: {}, refresh: async () => {} })

export const useChatUnread = () => useContext(Context)

/** Polls the user's unread Printerval chat and toasts which order has a new message. */
export function ChatUnreadProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const { showToast } = useToast()
  const [unread, setUnread] = useState<Record<string, ChatUnreadItem>>({})
  const seen = useRef<Map<string, number> | null>(null)
  const enabled = Boolean(user && CHAT_ROLES.includes(user.role))

  const refresh = useCallback(async () => {
    try {
      const { items } = await apiFetch<{ items: ChatUnreadItem[] }>('/chat/unread')
      setUnread(Object.fromEntries(items.map((i) => [i.order_id, i])))
      if (seen.current === null) {
        // First poll after loading the app: one summary instead of a toast per conversation.
        seen.current = new Map(items.map((i) => [i.order_id, i.latest_id]))
        if (items.length) showToast(`${items.length} đơn có tin chat mới từ Printerval.`, 'info', 8000)
        return
      }
      for (const item of items) {
        if ((seen.current.get(item.order_id) ?? 0) < item.latest_id) {
          seen.current.set(item.order_id, item.latest_id)
          showToast(`Đơn ${item.order_code} có tin nhắn mới trên Tacahu.`, 'info', 8000)
        }
      }
    } catch {
      // transient: the next poll retries
    }
  }, [showToast])

  useEffect(() => {
    if (!enabled) {
      seen.current = null
      setUnread({})
      return
    }
    void refresh()
    const timer = setInterval(() => void refresh(), POLL_MS)
    return () => clearInterval(timer)
  }, [enabled, refresh, user?.id])

  const value = useMemo(() => ({ unread, refresh }), [unread, refresh])
  return <Context.Provider value={value}>{children}</Context.Provider>
}

/** Small "n tin chat" pill for an order row; renders nothing when there is nothing unread. */
export function ChatBadge({ orderId }: { orderId: string }) {
  const { unread } = useChatUnread()
  const item = unread[orderId]
  if (!item) return null
  return (
    <span
      className="inline-flex items-center gap-1 rounded border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[10px] font-bold text-rose-700"
      title={`${item.sender_name}: ${item.snippet}`}
    >
      {item.count} tin chat
    </span>
  )
}
