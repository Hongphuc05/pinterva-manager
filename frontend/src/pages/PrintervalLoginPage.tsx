import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch, ApiError } from '../api/client'
import { DashboardLayout } from '../components/DashboardLayout'
import { Globe, CheckCircle2, AlertCircle, ArrowRight } from 'lucide-react'

export function PrintervalLoginPage() {
  const [sessionOpen, setSessionOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    apiFetch<{ session_open: boolean }>('/printerval-login/status')
      .then((r) => setSessionOpen(r.session_open))
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Không tải được trạng thái phiên Chrome.'))
      .finally(() => setLoading(false))
  }, [])

  async function handleStart() {
    setError(null)
    setBusy(true)
    try {
      const r = await apiFetch<{ session_open: boolean }>('/printerval-login/start', {
        method: 'POST',
      })
      setSessionOpen(r.session_open)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Không khởi chạy được trình duyệt Chrome.')
    } finally {
      setBusy(false)
    }
  }

  async function handleDone() {
    setError(null)
    setBusy(true)
    try {
      await apiFetch('/printerval-login/done', { method: 'POST' })
      navigate('/orders')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Không đóng được phiên đăng nhập.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <DashboardLayout>
      <div className="max-w-2xl mx-auto space-y-6 pt-4">
        {/* Header Info */}
        <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-6 shadow-xs space-y-2">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-blue-50 text-[#0052CC]">
              <Globe className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-800">Đăng Nhập Tài Khoản Printerval Công Ty</h1>
              <p className="text-xs text-slate-500">Kết nối trình duyệt Chrome thật để lưu cookie phiên làm việc dùng cho việc crawl đơn tự động</p>
            </div>
          </div>
        </div>

        {error && (
          <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs font-semibold flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0 text-red-600" />
            <span>{error}</span>
          </div>
        )}

        {/* Action Box */}
        <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-xs text-center space-y-6">
          <div className="h-16 w-16 bg-slate-50 border border-slate-200 rounded-2xl flex items-center justify-center mx-auto text-[#0052CC] shadow-inner">
            <Globe className="h-8 w-8" />
          </div>

          <div className="space-y-2 max-w-md mx-auto">
            <h2 className="text-base font-bold text-slate-800">
              {sessionOpen ? 'Cửa sổ Chrome Đang Mở...' : 'Khởi Chạy Trình Duyệt Chrome'}
            </h2>
            <p className="text-xs text-slate-500">
              {sessionOpen
                ? 'Đăng nhập vào tài khoản công ty trên cửa sổ Chrome vừa bật, sau đó nhấn "Hoàn Tất & Lưu Session" bên dưới để đóng cửa sổ.'
                : 'Bấm nút bên dưới để hệ thống mở cửa sổ Chrome tương tác. Sau khi mở, hãy thực hiện đăng nhập tài khoản Printerval admin.'}
            </p>
          </div>

          {/* Status Indicator Pill */}
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-100 text-slate-700 text-xs font-mono font-medium">
            <span className={`h-2 w-2 rounded-full ${sessionOpen ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'}`}></span>
            <span>Trạng thái phiên: {sessionOpen ? 'CHROME_ACTIVE' : 'READY'}</span>
          </div>

          {/* Action Buttons */}
          <div>
            {sessionOpen ? (
              <button
                onClick={handleDone}
                disabled={busy}
                className="px-6 py-3 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-xl transition-colors shadow-md flex items-center gap-2 mx-auto disabled:opacity-50"
              >
                <CheckCircle2 className="h-4 w-4" />
                <span>{busy ? 'Đang lưu phiên...' : 'Hoàn Tất & Lưu Session Cookie'}</span>
              </button>
            ) : (
              <button
                onClick={handleStart}
                disabled={busy || loading}
                className="px-6 py-3 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl transition-colors shadow-md flex items-center gap-2 mx-auto disabled:opacity-50"
              >
                <span>{busy ? 'Đang khởi chạy Chrome...' : 'Mở Trình Duyệt Chrome Để Đăng Nhập'}</span>
                <ArrowRight className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </DashboardLayout>
  )
}
