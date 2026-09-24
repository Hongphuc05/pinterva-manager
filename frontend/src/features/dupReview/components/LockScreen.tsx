import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Loader2, Lock } from 'lucide-react'
import { ApiError } from '../../../api/client'
import { setupPassword, unlockReview } from '../access'

const MIN = 6

/** Password gate of the hidden review area; the very first visit chooses the password. */
export function LockScreen({ firstUse, onUnlocked }: { firstUse: boolean; onUnlocked: () => void }) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (firstUse) {
      if (password.length < MIN) return setError(`Mật khẩu phải có ít nhất ${MIN} ký tự.`)
      if (password !== confirm) return setError('Hai mật khẩu chưa giống nhau.')
    }
    setBusy(true)
    try {
      if (firstUse) await setupPassword(password)
      else await unlockReview(password)
      onUnlocked()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không mở được. Thử lại.')
    } finally {
      setBusy(false)
    }
  }

  const field = 'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100'
  return (
    <div className="grid min-h-[100dvh] place-items-center bg-slate-50 p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5 flex items-center gap-3">
          <div className="rounded-lg bg-blue-600 p-2 text-white shadow-sm">
            <Lock className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-base font-bold leading-tight text-slate-900">Khu vực duyệt trùng</h1>
            <p className="text-xs text-slate-500">{firstUse ? 'Đặt mật khẩu cho khu vực này' : 'Nhập mật khẩu để mở'}</p>
          </div>
        </div>

        <label htmlFor="review-password" className="mb-1 block text-xs font-semibold text-slate-600">
          {firstUse ? 'Mật khẩu mới' : 'Mật khẩu'}
        </label>
        <input
          id="review-password"
          type="password"
          autoFocus
          autoComplete={firstUse ? 'new-password' : 'current-password'}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={field}
        />
        {firstUse && (
          <>
            <label htmlFor="review-confirm" className="mb-1 mt-3 block text-xs font-semibold text-slate-600">Nhập lại mật khẩu</label>
            <input id="review-confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} className={field} />
            <p className="mt-2 text-[11px] text-slate-500">Mật khẩu dùng chung cho cả nhóm Support, đổi được ở mục Cài đặt sau khi vào.</p>
          </>
        )}

        {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs font-medium text-red-700">{error}</p>}

        <button
          type="submit"
          disabled={busy || !password}
          className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50"
        >
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          {firstUse ? 'Đặt mật khẩu và vào' : 'Mở'}
        </button>
        <Link to="/orders" className="mt-4 inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-800">
          <ArrowLeft className="h-3.5 w-3.5" />Về hệ thống
        </Link>
      </form>
    </div>
  )
}
