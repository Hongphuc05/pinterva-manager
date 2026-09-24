import { useState, type FormEvent } from 'react'
import { KeyRound, Loader2, Lock } from 'lucide-react'
import { ApiError } from '../../../api/client'
import { changePassword } from '../access'
import { useToast } from '../toast'

const MIN = 6

export function SettingsView({ onLock }: { onLock: () => void }) {
  const toast = useToast()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (next.length < MIN) return setError(`Mật khẩu mới phải có ít nhất ${MIN} ký tự.`)
    if (next !== confirm) return setError('Hai mật khẩu mới chưa giống nhau.')
    setBusy(true)
    try {
      await changePassword(current, next)
      setCurrent('')
      setNext('')
      setConfirm('')
      toast('Đã đổi mật khẩu. Các phiên đang mở ở nơi khác sẽ phải nhập lại.')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không đổi được mật khẩu.')
    } finally {
      setBusy(false)
    }
  }

  const field = 'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100'
  return (
    <div className="max-w-xl space-y-5">
      <form onSubmit={submit} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-2 flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-slate-500" />
          <h2 className="text-sm font-bold text-slate-900">Đổi mật khẩu khu vực này</h2>
        </div>
        <p className="mb-4 text-xs text-slate-500">Mật khẩu dùng chung cho cả nhóm Support. Sau khi đổi, các phiên đang mở ở máy khác sẽ bị khóa lại.</p>
        <div className="space-y-3">
          <div>
            <label htmlFor="pw-current" className="mb-1 block text-xs font-semibold text-slate-600">Mật khẩu hiện tại</label>
            <input id="pw-current" type="password" autoComplete="current-password" className={field} value={current} onChange={(e) => setCurrent(e.target.value)} />
          </div>
          <div>
            <label htmlFor="pw-new" className="mb-1 block text-xs font-semibold text-slate-600">Mật khẩu mới</label>
            <input id="pw-new" type="password" autoComplete="new-password" className={field} value={next} onChange={(e) => setNext(e.target.value)} />
          </div>
          <div>
            <label htmlFor="pw-confirm" className="mb-1 block text-xs font-semibold text-slate-600">Nhập lại mật khẩu mới</label>
            <input id="pw-confirm" type="password" autoComplete="new-password" className={field} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </div>
        </div>
        {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs font-medium text-red-700">{error}</p>}
        <button
          type="submit"
          disabled={busy || !current || !next || !confirm}
          className="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50"
        >
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}Đổi mật khẩu
        </button>
      </form>

      <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Khóa khu vực này</h2>
          <p className="mt-0.5 text-xs text-slate-500">Lần sau vào lại phải nhập mật khẩu.</p>
        </div>
        <button
          type="button"
          onClick={onLock}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
        >
          <Lock className="h-3.5 w-3.5" />Khóa ngay
        </button>
      </div>
    </div>
  )
}
