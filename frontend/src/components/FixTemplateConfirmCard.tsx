import { useState } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { apiFetch } from '../api/client'
import { LinkifiedText } from './LinkifiedText'

export type FixTemplateConfirm = {
  round: number | null
  url: string | null
  note: string | null
  requested_at: string
}

/**
 * Admin: Printerval keeps an order in Fix raised for "Đổi template" until someone says whether the Fix
 * really was about the template. The answer is sent with the next Review push.
 */
export function FixTemplateConfirmCard({
  orderId,
  request,
  onDone,
}: {
  orderId: string
  request: FixTemplateConfirm
  onDone: () => void
}) {
  const [disputing, setDisputing] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function answer(decision: 'agree' | 'disagree') {
    if (decision === 'disagree' && !note.trim()) {
      setError('Ghi giải thích vì sao không phải đổi template.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await apiFetch(`/orders/${orderId}/printerval-template-confirm`, {
        method: 'POST',
        body: JSON.stringify({ decision, note: decision === 'disagree' ? note.trim() : undefined, request_id: crypto.randomUUID() }),
      })
      onDone()
    } catch (caught: any) {
      setError(caught?.message || 'Không gửi được xác nhận.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-xl border border-red-200 bg-red-50/70 p-4 text-xs space-y-2" aria-label="Xác nhận Fix do đổi template">
      <h3 className="flex items-center gap-1.5 font-bold text-red-900">
        <AlertTriangle className="h-4 w-4 text-red-600" />
        Printerval cần xác nhận Fix do đổi template{request.round ? ` (lần ${request.round})` : ''}
      </h3>
      <p className="text-slate-700">Đơn không chuyển được sang Review cho tới khi trả lời. Trả lời xong, Tacahu tự gửi lại Review lên Printerval.</p>
      {request.url && (
        <p><strong>Link template:</strong> <LinkifiedText text={request.url} /></p>
      )}
      {request.note && (
        <p className="whitespace-pre-wrap"><strong>Ghi chú QC:</strong> <LinkifiedText text={request.note} /></p>
      )}
      {disputing && (
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          maxLength={500}
          rows={3}
          placeholder="Vì sao không phải đổi template (bắt buộc)"
          className="w-full rounded-lg border border-slate-300 bg-white p-2 text-xs focus:border-red-500 focus:outline-none"
        />
      )}
      {error && <p className="rounded bg-white px-2 py-1 text-red-700">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => void answer('agree')}
          className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 font-bold text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Xác nhận Fix do đổi template
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => (disputing ? void answer('disagree') : setDisputing(true))}
          className="rounded-lg bg-amber-500 px-3 py-1.5 font-bold text-white hover:bg-amber-600 disabled:opacity-50"
        >
          {disputing ? 'Gửi: không phải đổi template' : 'Không đúng, không phải đổi template'}
        </button>
      </div>
    </section>
  )
}
