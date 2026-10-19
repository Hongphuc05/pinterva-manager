import { useEffect, useState } from 'react'
import { Loader2, MessageSquare, RefreshCw } from 'lucide-react'
import { apiFetch } from '../api/client'
import { LinkifiedText } from './LinkifiedText'

type ChatMessage = {
  id: number
  fix_round: number
  type: string
  sender_name: string
  mine: boolean
  content: string
  image_urls: string[]
  fix_reason_label: string
  sent_at: string | null
}

/** Admin only: the conversation of one order on Printerval, fetched when the order is opened (nothing is stored). */
export function PrintervalChatCard({ orderId }: { orderId: string }) {
  const [messages, setMessages] = useState<ChatMessage[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    try {
      const data = await apiFetch<{ messages: ChatMessage[] }>(`/orders/${orderId}/printerval-chat`)
      setMessages(data.messages)
      setError(null)
    } catch (caught: any) {
      setError(caught?.message || 'Không tải được chat từ Printerval, thử lại sau')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setMessages(null)
    void load()
  }, [orderId])

  return (
    <div className="p-4 rounded-xl bg-amber-50/60 border border-amber-100 text-xs space-y-2" aria-label="Chat Printerval">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-bold text-slate-800 flex items-center gap-1.5">
          <MessageSquare className="h-4 w-4 text-amber-600" />
          <span>Chat Printerval</span>
        </h3>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex items-center gap-1 text-slate-500 hover:text-slate-800 disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Tải lại
        </button>
      </div>
      {error && <p className="rounded bg-red-50 p-2 text-red-700">{error}</p>}
      {messages && messages.length === 0 && <p className="text-slate-500">Chưa có tin nhắn nào.</p>}
      <ul className="space-y-2">
        {(messages ?? []).map((message) => (
          <li
            key={message.id}
            className={`rounded-lg border p-2 ${message.mine ? 'bg-white border-slate-200 ml-6' : 'bg-white border-amber-200 mr-6'}`}
          >
            <div className="flex flex-wrap items-center gap-x-2 text-[11px] text-slate-500">
              <span className="font-semibold text-slate-700">{message.mine ? 'Tacahu/Outsource' : message.sender_name || 'Printerval'}</span>
              {message.type === 'fix_open' && (
                <span className="rounded bg-red-100 px-1.5 text-red-700">Mở Fix vòng {message.fix_round}</span>
              )}
              {message.sent_at && <span>{new Date(message.sent_at).toLocaleString('vi-VN')}</span>}
            </div>
            {message.fix_reason_label && <p className="mt-1 font-semibold text-red-700">{message.fix_reason_label}</p>}
            {message.content && (
              <p className="mt-1 whitespace-pre-wrap text-slate-800">
                <LinkifiedText text={message.content} />
              </p>
            )}
            {message.image_urls.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {message.image_urls.map((url) => (
                  <a key={url} href={url} target="_blank" rel="noreferrer noopener">
                    <img src={url} alt="Ảnh trong chat" loading="lazy" className="h-16 w-16 rounded border border-slate-200 object-cover" />
                  </a>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
