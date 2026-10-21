import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Flag, Loader2, RotateCcw, Scale, X } from 'lucide-react'
import { apiFetch, ApiError } from '../api/client'

/** "Báo fix không đúng" as stored on the order (see app/application/fix_dispute.py). */
export type FixDisputeRecord = {
  round: number
  note: string | null
  images: string[]
  submitted_by_name?: string | null
  submitted_at?: string | null
  source?: string
  push: 'queued' | 'sent' | 'failed'
  push_error?: string | null
  remote_status?: string | null
  arbiter_note?: string | null
  outcome?: 'accepted' | 'rejected' | null
}

// Printerval's own limits (read from its page on 21/10/2026).
const NOTE_MIN = 10
const NOTE_MAX = 1000
const IMAGES_MAX = 5

function splitLinks(text: string): string[] {
  return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
}

function problem(note: string, links: string[]): string | null {
  if (note.trim().length < NOTE_MIN) return `Ghi rõ vì sao FIX không đúng (ít nhất ${NOTE_MIN} ký tự).`
  if (links.length > IMAGES_MAX) return `Tối đa ${IMAGES_MAX} link ảnh.`
  if (links.some((url) => !/^https?:\/\/\S+$/i.test(url))) return 'Link ảnh phải bắt đầu bằng http:// hoặc https://'
  return null
}

/** The same form as Printerval's "Báo FIX không đúng" modal; sent to Printerval in the background. */
export function FixDisputeModal({
  orderId,
  orderVersion,
  externalOrderId,
  onClose,
  onSent,
}: {
  orderId: string
  orderVersion?: number
  externalOrderId: string
  onClose: () => void
  onSent: () => void
}) {
  const [note, setNote] = useState('')
  const [linksText, setLinksText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !sending) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, sending])

  async function send() {
    const links = splitLinks(linksText)
    const issue = problem(note, links)
    if (issue) {
      setError(issue)
      return
    }
    setSending(true)
    setError(null)
    try {
      await apiFetch(`/orders/${orderId}/fix-dispute`, {
        method: 'POST',
        body: JSON.stringify({
          note: note.trim(),
          images: links,
          ...(typeof orderVersion === 'number' ? { expected_version: orderVersion } : {}),
        }),
      })
      onSent()
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không gửi được khiếu nại.')
    } finally {
      setSending(false)
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-[999999] flex items-center justify-center bg-black/50 p-4" onClick={() => !sending && onClose()}>
      <div
        role="dialog"
        aria-label={`Báo FIX không đúng ${externalOrderId}`}
        className="flex w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-amber-100 bg-amber-50/80 px-5 py-4">
          <h3 className="flex items-center gap-2 text-sm font-bold text-slate-900">
            <Flag className="h-4 w-4 text-amber-600" />
            {externalOrderId} — Báo FIX không đúng
          </h3>
          <button type="button" onClick={onClose} disabled={sending} aria-label="Đóng" className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-4 p-5 text-xs">
          <p className="text-sky-700">
            Người review khác sẽ phân xử. Đúng là fix sai thì lần fix này không tính vào tỉ lệ fix/phạt. Khiếu nại sai thì job quay lại FIX và vẫn tính như cũ.
          </p>
          {error && <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-red-700">{error}</p>}
          <label className="block space-y-1.5">
            <span className="flex items-center justify-between font-bold text-slate-800">
              <span>Vì sao FIX không đúng (bắt buộc)</span>
              <span className={`font-mono font-normal ${note.trim().length < NOTE_MIN ? 'text-slate-400' : 'text-emerald-600'}`}>
                {note.trim().length}/{NOTE_MAX}
              </span>
            </span>
            <textarea
              rows={4}
              maxLength={NOTE_MAX}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="w-full rounded-xl border border-slate-300 p-3 leading-relaxed focus:outline-none focus:ring-2 focus:ring-amber-500"
            />
          </label>
          <label className="block space-y-1.5">
            <span className="font-semibold text-slate-700">Link ảnh chứng minh (không bắt buộc, mỗi dòng một link, tối đa {IMAGES_MAX})</span>
            <textarea
              rows={3}
              value={linksText}
              onChange={(e) => setLinksText(e.target.value)}
              placeholder="https://..."
              className="w-full rounded-xl border border-slate-300 p-3 font-mono focus:outline-none focus:ring-2 focus:ring-amber-500"
            />
          </label>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-slate-100 bg-slate-50 px-5 py-3">
          <button
            type="button"
            onClick={() => void send()}
            disabled={sending}
            className="inline-flex items-center gap-1.5 rounded-xl bg-amber-500 px-4 py-2 text-xs font-bold text-white shadow-xs hover:bg-amber-600 disabled:opacity-50"
          >
            {sending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Gửi khiếu nại
          </button>
          <button type="button" onClick={onClose} disabled={sending} className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100">
            Huỷ
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/** Where the Admin's dispute stands; a failed push can be sent again from here. */
export function FixDisputeBadge({
  dispute,
  orderId,
  orderVersion,
  onRetried,
}: {
  dispute: FixDisputeRecord | null | undefined
  orderId: string
  orderVersion?: number
  onRetried?: () => void
}) {
  const [retrying, setRetrying] = useState(false)
  const [retryError, setRetryError] = useState<string | null>(null)
  if (!dispute) return null

  async function retry() {
    setRetrying(true)
    setRetryError(null)
    try {
      await apiFetch(`/orders/${orderId}/fix-dispute/retry`, {
        method: 'POST',
        body: JSON.stringify(typeof orderVersion === 'number' ? { expected_version: orderVersion } : {}),
      })
      onRetried?.()
    } catch (err) {
      setRetryError(err instanceof ApiError ? err.message : 'Không gửi lại được.')
    } finally {
      setRetrying(false)
    }
  }

  const base = 'inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-bold'
  if (dispute.outcome === 'rejected' || dispute.remote_status === 'rejected') {
    return (
      <span className={`${base} border-rose-200 bg-rose-50 text-rose-700`} title={dispute.arbiter_note ?? ''}>
        <Scale className="h-3.5 w-3.5" />
        Khiếu nại bị bác — FIX đúng{dispute.arbiter_note ? `: ${dispute.arbiter_note}` : ''}
      </span>
    )
  }
  if (dispute.outcome === 'accepted') {
    return (
      <span className={`${base} border-emerald-200 bg-emerald-50 text-emerald-700`}>
        <Scale className="h-3.5 w-3.5" />
        Khiếu nại được chấp nhận (fix sai, không tính)
      </span>
    )
  }
  if (dispute.push === 'failed') {
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <span className={`${base} border-red-200 bg-red-50 text-red-700`} title={dispute.push_error ?? ''}>
          Gửi khiếu nại lỗi{dispute.push_error ? `: ${dispute.push_error}` : ''}
        </span>
        <button
          type="button"
          onClick={() => void retry()}
          disabled={retrying}
          className={`${base} cursor-pointer border-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-50`}
        >
          {retrying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
          Gửi lại
        </button>
        {retryError && <span className="text-[11px] text-red-600">{retryError}</span>}
      </span>
    )
  }
  if (dispute.push === 'queued') {
    return (
      <span className={`${base} border-amber-200 bg-amber-50 text-amber-700`}>
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Đang gửi khiếu nại
      </span>
    )
  }
  return (
    <span className={`${base} border-amber-200 bg-amber-50 text-amber-800`} title={dispute.note ?? ''}>
      <Flag className="h-3.5 w-3.5" />
      Đang chờ phân xử khiếu nại
    </span>
  )
}
