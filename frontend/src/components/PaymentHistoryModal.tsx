import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, ChevronRight, History, Loader2, X } from 'lucide-react'
import { ApiError } from '../api/client'
import { fetchPaymentHistory, type PaymentBatch } from '../features/payments/api'
import { useToast } from '../context/ToastContext'

const money = (n: number) => `${n.toLocaleString('vi-VN')} đ`
const when = (iso: string) => new Date(iso).toLocaleString('vi-VN')

/** Who paid which Designer, how many orders, how much, when. Shared by Admin and Accountant;
 * the server itself hides the per-order rate from anyone but Admin (batch total is always shown). */
export function PaymentHistoryModal({ onClose }: { onClose: () => void }) {
  const { showToast: toast } = useToast()
  const [batches, setBatches] = useState<PaymentBatch[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    fetchPaymentHistory()
      .then((res) => setBatches(res.batches))
      .catch((err) => toast(err instanceof ApiError ? err.message : 'Không tải được lịch sử thanh toán.', 'error'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/70 p-4" onClick={onClose}>
      <div
        data-testid="payment-history-modal"
        className="flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-5 py-4">
          <div className="flex items-center gap-2">
            <History className="h-5 w-5 text-[#0052CC]" />
            <h3 className="text-sm font-bold text-slate-900">Lịch sử thanh toán</h3>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-200 hover:text-slate-700" aria-label="Đóng">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {!batches ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500">
              <Loader2 className="h-5 w-5 animate-spin" />Đang tải...
            </div>
          ) : batches.length === 0 ? (
            <p className="py-16 text-center text-sm text-slate-500">Chưa có lần thanh toán nào.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {batches.map((b) => {
                const expanded = open === b.id
                return (
                  <li key={b.id}>
                    <button
                      type="button"
                      onClick={() => setOpen(expanded ? null : b.id)}
                      className="flex w-full items-center justify-between gap-3 px-5 py-3 text-left hover:bg-slate-50"
                    >
                      <div className="flex items-center gap-2">
                        {expanded ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
                        <div>
                          <p className="text-sm font-bold text-slate-900">{b.designer_name}</p>
                          <p className="text-xs text-slate-500">
                            {b.paid_by_name} đã thanh toán · {when(b.paid_at)}
                            {b.source === 'backfill' && <span className="ml-1.5 text-slate-400">(dựng lại)</span>}
                          </p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-bold text-slate-900">{money(b.total_amount)}</p>
                        <p className="text-xs text-slate-500">{b.order_count} đơn</p>
                      </div>
                    </button>
                    {expanded && (
                      <ul className="space-y-1 bg-slate-50 px-5 py-3 text-xs">
                        {b.items.map((item) => (
                          <li key={item.order_id} className="flex items-center justify-between gap-2 text-slate-600">
                            <span className="truncate">
                              <span className="font-mono font-semibold text-slate-800">{item.external_order_id}</span>
                              {item.product_name && <span className="text-slate-400"> · {item.product_name}</span>}
                            </span>
                            {item.amount !== null && <span className="flex-none font-semibold">{money(item.amount)}</span>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
