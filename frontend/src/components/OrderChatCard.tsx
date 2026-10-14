import { useEffect, useState } from 'react'
import { Loader2, MessageSquare } from 'lucide-react'
import { ApiError, apiFetch } from '../api/client'
import { useChatUnread } from '../features/chat/ChatUnreadProvider'
import { LinkifiedText } from './LinkifiedText'

interface ChatMessage {
  id: number
  type: string
  sender_type: string
  sender_name: string
  mine: boolean
  content: string
  image_urls: string[]
  fix_round: number
  fix_reason_label: string
  sent_at: string
}

interface ChatPayload {
  stale: boolean
  last_read_external_id: number
  messages: ChatMessage[]
}

const REFRESH_MS = 30_000

/** The Printerval chat of this order, read only, as Printerval shows it. */
export function OrderChatCard({ orderId }: { orderId: string }) {
  const { refresh } = useChatUnread()
  const [data, setData] = useState<ChatPayload | null>(null)
  const [hidden, setHidden] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const payload = await apiFetch<ChatPayload>(`/orders/${orderId}/chat`)
        if (!alive) return
        setData(payload)
        setError(null)
        const newest = payload.messages.at(-1)?.id ?? 0
        if (newest > payload.last_read_external_id) {
          await apiFetch(`/orders/${orderId}/chat/read`, { method: 'POST' })
          void refresh()
        }
      } catch (e) {
        if (!alive) return
        if (e instanceof ApiError && (e.status === 403 || e.status === 404)) setHidden(true)
        else setError(e instanceof Error ? e.message : 'Không tải được chat.')
      }
    }
    void load()
    const timer = setInterval(() => void load(), REFRESH_MS)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [orderId, refresh])

  if (hidden) return null
  const fmt = (iso: string) =>
    new Date(iso).toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

  return (
    <section className="space-y-3 border-t border-slate-100 pt-4" data-testid="order-chat">
      <h3 className="flex items-center gap-2 text-xs font-bold text-slate-700">
        <MessageSquare className="h-3.5 w-3.5 text-[#0052CC]" />
        Chat với Printerval
        {data?.stale && <span className="font-medium text-amber-600">(chưa cập nhật được, đang hiện tin đã lưu)</span>}
      </h3>
      {!data && !error && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
      {error && <p className="text-xs text-rose-600">{error}</p>}
      {data && data.messages.length === 0 && <p className="text-xs text-slate-500">Chưa có tin nhắn.</p>}
      {data && data.messages.length > 0 && (
        <ul className="max-h-96 space-y-2 overflow-y-auto rounded-xl bg-slate-50 p-3">
          {data.messages.map((m) => (
            <li key={m.id} className={`flex ${m.mine ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[85%] rounded-xl border px-3 py-2 text-xs ${
                  m.mine ? 'border-emerald-200 bg-emerald-50' : 'border-slate-200 bg-white'
                }`}
              >
                <div className="mb-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-slate-500">
                  <b className="text-slate-800">{m.sender_name || 'Printerval'}</b>
                  <span>{fmt(m.sent_at)}</span>
                  {m.type === 'fix_open' && (
                    <span className="rounded bg-amber-100 px-1.5 font-bold text-amber-800">Fix vòng {m.fix_round}</span>
                  )}
                </div>
                {m.fix_reason_label && <p className="font-semibold text-amber-800">{m.fix_reason_label}</p>}
                {m.content && (
                  <p className="whitespace-pre-wrap break-words text-slate-800">
                    <LinkifiedText text={m.content} />
                  </p>
                )}
                {m.image_urls.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-2">
                    {m.image_urls.map((url) => (
                      <a key={url} href={url} target="_blank" rel="noreferrer">
                        <img
                          src={url}
                          alt="Ảnh trong chat"
                          referrerPolicy="no-referrer"
                          className="h-20 w-20 rounded-lg border border-slate-200 object-cover"
                        />
                      </a>
                    ))}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
