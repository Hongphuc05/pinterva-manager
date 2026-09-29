import { useCallback, useEffect, useState } from 'react'
import { History, LogOut, QrCode, RefreshCw, Wallet } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { useToast } from '../context/ToastContext'
import { ApiError } from '../api/client'
import { fetchPendingDesigners, type PendingDesigner } from '../features/payments/api'
import { DesignerPayModal } from '../components/DesignerPayModal'
import { PaymentHistoryModal } from '../components/PaymentHistoryModal'

const money = (n: number) => `${n.toLocaleString('vi-VN')} đ`

/**
 * The Accountant's one and only page: Designers waiting for payment, click a row to see their
 * orders and pay. No other menu — the account is otherwise locked out of the site (see
 * ACCOUNTANT_ALLOWED in app/api/deps.py).
 */
export function AccountantPaymentsPage() {
  const { user, logout } = useAuth()
  const { showToast: toast } = useToast()
  const [rows, setRows] = useState<PendingDesigner[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await fetchPendingDesigners())
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Không tải được danh sách.', 'error')
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="min-h-[100dvh] bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-slate-200 bg-white px-4 shadow-sm md:px-6">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-[#0052CC] p-2 text-white shadow-sm">
            <Wallet className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-base font-bold leading-tight text-slate-900">Thanh toán tiền công</h1>
            <p className="hidden text-[11px] font-medium text-slate-500 sm:block">{user?.full_name || user?.username}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setHistoryOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            <History className="h-3.5 w-3.5" />Lịch sử
          </button>
          <button
            type="button"
            onClick={() => void logout()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-bold text-white shadow-sm transition hover:bg-slate-700"
          >
            <LogOut className="h-3.5 w-3.5" />Đăng xuất
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-3xl p-4 md:p-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-bold text-slate-700">Chờ thanh toán ({rows?.length ?? 0} designer)</h2>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 shadow-sm transition hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />Làm mới
          </button>
        </div>

        {!rows ? (
          <div className="rounded-xl border border-slate-200 bg-white py-16 text-center text-sm text-slate-500">Đang tải...</div>
        ) : rows.length === 0 ? (
          <div className="rounded-xl border border-slate-200 bg-white py-16 text-center text-sm text-slate-500">
            Không có đơn nào chờ thanh toán.
          </div>
        ) : (
          <ul className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            {rows.map((r) => (
              <li key={r.designer_id} className="border-b border-slate-100 last:border-0">
                <button
                  type="button"
                  onClick={() => setSelected(r.designer_id)}
                  className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left transition hover:bg-slate-50"
                >
                  <div className="flex items-center gap-2.5">
                    <div>
                      <p className="text-sm font-bold text-slate-900">{r.designer_name}</p>
                      <p className="text-xs text-slate-500">{r.pending_count} đơn chờ thanh toán</p>
                    </div>
                    {!r.has_qr && (
                      <span title="Chưa có QR ngân hàng" className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700 ring-1 ring-amber-200">
                        <QrCode className="h-3 w-3" />Chưa có QR
                      </span>
                    )}
                  </div>
                  <span className="flex-none text-sm font-bold text-slate-900">{money(r.pending_amount)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </main>

      {selected && (
        <DesignerPayModal
          designerId={selected}
          onClose={() => setSelected(null)}
          onPaid={() => void load()}
        />
      )}
      {historyOpen && <PaymentHistoryModal onClose={() => setHistoryOpen(false)} />}
    </div>
  )
}
