import { useEffect, useState } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { apiFetch } from '../api/client'
import { LinkifiedText } from './LinkifiedText'

type TemplateRequest = {
  round: number | null
  url: string | null
  note: string | null
  decision?: 'agree' | 'disagree' | null
  decision_note?: string | null
}

export type FixTemplateAnswer = {
  request: TemplateRequest | null
  loading: boolean
  decision: 'agree' | 'disagree' | null
  setDecision: (value: 'agree' | 'disagree') => void
  note: string
  setNote: (value: string) => void
  /** Why the Fix cannot be accepted yet, or null. */
  problem: string | null
  /** Fields to send with the approval (nothing when Printerval asks no template question). */
  payload: () => { template_confirm?: string; template_confirm_note?: string }
}

/**
 * Admin: Printerval asks whether a Fix raised for "Đổi template" really was about the template. The answer
 * is given while accepting the Fix and sent to Printerval with the Designer's Review, so the order can
 * leave Fix without a second step. Null request = an ordinary Fix.
 */
export function useFixTemplate(orderId: string | null): FixTemplateAnswer {
  const [request, setRequest] = useState<TemplateRequest | null>(null)
  const [loading, setLoading] = useState(false)
  const [decision, setDecision] = useState<'agree' | 'disagree' | null>(null)
  const [note, setNote] = useState('')

  useEffect(() => {
    setRequest(null)
    setDecision(null)
    setNote('')
    if (!orderId) return
    let alive = true
    setLoading(true)
    apiFetch<{ request: TemplateRequest | null }>(`/orders/${orderId}/fix-template`)
      .then((data) => {
        if (!alive) return
        const asked = data?.request ?? null
        setRequest(asked)
        if (asked?.decision) {
          setDecision(asked.decision)
          setNote(asked.decision_note || '')
        }
      })
      .catch(() => {})
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [orderId])

  const problem = !request
    ? null
    : !decision
      ? 'Printerval hỏi Fix này có phải do đổi template không: hãy chọn xác nhận hoặc không đúng.'
      : decision === 'disagree' && !note.trim()
        ? 'Hãy ghi giải thích vì sao không phải đổi template.'
        : null

  return {
    request,
    loading,
    decision,
    setDecision,
    note,
    setNote,
    problem,
    payload: () =>
      request && decision
        ? { template_confirm: decision, ...(decision === 'disagree' ? { template_confirm_note: note.trim() } : {}) }
        : {},
  }
}

export function FixTemplateQuestion({ state }: { state: FixTemplateAnswer }) {
  const { request, loading, decision, setDecision, note, setNote } = state
  if (loading && !request) {
    return (
      <p className="inline-flex items-center gap-1.5 text-[11px] text-slate-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Đang kiểm tra yêu cầu xác nhận đổi template…
      </p>
    )
  }
  if (!request) return null
  const pick = (value: 'agree' | 'disagree') =>
    `rounded-lg px-3 py-1.5 text-xs font-bold border cursor-pointer ${
      decision === value
        ? value === 'agree'
          ? 'bg-emerald-600 text-white border-emerald-600'
          : 'bg-amber-500 text-white border-amber-500'
        : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
    }`
  return (
    <section className="rounded-xl border border-red-200 bg-red-50/70 p-3 text-xs space-y-2" aria-label="Xác nhận Fix do đổi template">
      <h4 className="flex items-center gap-1.5 font-bold text-red-900">
        <AlertTriangle className="h-4 w-4 text-red-600 shrink-0" />
        Fix do đổi template{request.round ? ` (lần ${request.round})` : ''}: cần xác nhận
      </h4>
      {request.url && (
        <p className="break-all"><strong>Link template:</strong> <LinkifiedText text={request.url} /></p>
      )}
      {request.note && (
        <p className="whitespace-pre-wrap"><strong>Ghi chú:</strong> <LinkifiedText text={request.note} /></p>
      )}
      <div className="flex flex-wrap gap-2">
        <button type="button" className={pick('agree')} onClick={() => setDecision('agree')}>
          Xác nhận Fix do đổi template
        </button>
        <button type="button" className={pick('disagree')} onClick={() => setDecision('disagree')}>
          Không đúng, không phải đổi template
        </button>
      </div>
      {decision === 'disagree' && (
        <label className="block space-y-1">
          <span className="font-semibold text-slate-800">Giải thích (bắt buộc) — vì sao không phải đổi template</span>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={500}
            rows={3}
            className="w-full rounded-lg border border-slate-300 bg-white p-2 text-xs focus:border-amber-500 focus:outline-none"
          />
        </label>
      )}
    </section>
  )
}
