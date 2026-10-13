import { useEffect, useState } from 'react'
import { Loader2, Send } from 'lucide-react'
import { fetchTelegramAdmins, sendLot, tagLot, type TagResult, type TelegramAdmin } from '../api'
import type { Item, TabKey } from '../types'
import { useToast } from '../toast'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

const button =
  'inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-bold shadow-sm transition disabled:cursor-not-allowed disabled:opacity-50'

interface Props {
  jobId: string
  items: Item[]
  tab: TabKey
  onChanged: () => Promise<unknown>
}

/** The lot's bulk actions: send the chosen pairs to Telegram, then move the verified orders. */
export function LotPanel({ jobId, items, tab, onChanged }: Props) {
  const toast = useToast()
  const [admins, setAdmins] = useState<TelegramAdmin[] | null>(null)
  const [adminId, setAdminId] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [again, setAgain] = useState(false)

  useEffect(() => {
    if (tab !== 'pending' || admins !== null) return
    fetchTelegramAdmins()
      .then((list) => {
        setAdmins(list)
        setAdminId(list[0]?.id ?? '')
      })
      .catch(() => setAdmins([]))
  }, [tab, admins])

  const count = (stage: Item['stage']) => items.filter((i) => i.stage === stage).length
  const unsent = count('unsent')
  const waiting = count('waiting')
  // Orders Admin already gave to a designer cannot be tagged by Support: they are not counted.
  const verified = items.filter((i) => i.stage === 'verified' && i.taggable !== false).length
  const verifiedGiven = count('verified') - verified
  const notDuplicate = items.filter((i) => i.stage === 'not_duplicate' && i.taggable !== false).length
  const sendable = unsent + (again ? waiting : 0)

  const run = async (key: string, action: () => Promise<string>) => {
    setBusy(key)
    try {
      toast(await action())
      await onChanged()
    } catch (e) {
      toast(message(e), 'error')
    } finally {
      setBusy(null)
    }
  }

  const send = (target: 'support' | 'admin') =>
    run(`send-${target}`, async () => {
      const res = await sendLot(jobId, target, target === 'admin' ? adminId : undefined, again)
      return `Đã gửi ${res.sent} đơn qua Telegram.`
    })

  const tag = (to: 'duplicate' | 'non_duplicate') => {
    const n = to === 'duplicate' ? verified : notDuplicate
    const label = to === 'duplicate' ? 'Trùng lặp' : 'Không trùng lặp'
    if (!window.confirm(`Chuyển ${n} đơn sang ${label}?`)) return
    return run(`tag-${to}`, async () => {
      const res: TagResult = await tagLot(jobId, to)
      const shown = res.skipped.slice(0, 5).map((s) => `${s.order_code} (${s.reason})`).join(', ')
      const skipped = res.skipped.length
        ? ` Bỏ qua ${res.skipped.length}: ${shown}${res.skipped.length > 5 ? '…' : ''}.`
        : ''
      return `Đã chuyển ${res.moved} đơn sang ${label}.${skipped}`
    })
  }

  if (tab === 'pending') {
    const adminMissing = admins !== null && admins.length === 0
    return (
      <div className="mb-3 space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="lot-pending">
        <p className="text-xs text-slate-600">
          <b>{unsent}</b> chưa gửi · <b>{waiting}</b> đang chờ · <b>{count('verified')}</b> đã verify trùng
        </p>
        {waiting > 0 && (
          <label className="flex items-center gap-2 text-xs text-slate-700">
            <input type="checkbox" checked={again} onChange={(e) => setAgain(e.target.checked)} />
            Gửi cả {waiting} đơn đang chờ (gửi lại, người đầu tiên bấm sẽ quyết định)
          </label>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy !== null || sendable === 0}
            onClick={() => void send('support')}
            className={`${button} bg-blue-600 text-white hover:bg-blue-700`}
          >
            {busy === 'send-support' ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
            Gửi cho Support
          </button>
          <span className="text-xs text-slate-400">hoặc</span>
          <select
            aria-label="Admin nhận"
            value={adminId}
            onChange={(e) => setAdminId(e.target.value)}
            disabled={adminMissing}
            className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs"
          >
            {adminMissing && <option value="">Chưa có Admin nào liên kết Telegram</option>}
            {admins?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {a.telegram_username ? ` (@${a.telegram_username})` : ''}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={busy !== null || sendable === 0 || !adminId}
            onClick={() => void send('admin')}
            className={`${button} bg-slate-900 text-white hover:bg-slate-700`}
          >
            {busy === 'send-admin' ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
            Gửi cho Admin
          </button>
        </div>
        {sendable === 0 && (
          <p className="text-xs text-slate-500">
            {waiting > 0
              ? 'Mọi đơn đã được gửi và đang chờ trả lời. Tick ô trên nếu muốn gửi lại cho người khác.'
              : 'Không có đơn nào cần gửi.'}
          </p>
        )}
        <button
          type="button"
          disabled={busy !== null || verified === 0}
          onClick={() => void tag('duplicate')}
          className={`${button} bg-emerald-600 text-white hover:bg-emerald-700`}
        >
          {busy === 'tag-duplicate' && <Loader2 className="size-3.5 animate-spin" />}
          Chuyển toàn bộ đơn đã verify thành Trùng lặp ({verified})
        </button>
        {verifiedGiven > 0 && (
          <p className="text-xs text-slate-500">{verifiedGiven} đơn đã verify nhưng Admin đã chia cho designer, Support không chuyển được.</p>
        )}
      </div>
    )
  }

  if (tab === 'notdup') {
    return (
      <div className="mb-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="lot-notdup">
        <button
          type="button"
          disabled={busy !== null || notDuplicate === 0}
          onClick={() => void tag('non_duplicate')}
          className={`${button} bg-emerald-600 text-white hover:bg-emerald-700`}
        >
          {busy === 'tag-non_duplicate' && <Loader2 className="size-3.5 animate-spin" />}
          Chuyển toàn bộ thành Không trùng lặp ({notDuplicate})
        </button>
      </div>
    )
  }
  return null
}
