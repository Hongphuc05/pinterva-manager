import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { CheckCircle2, Image as ImageIcon, Loader2, X } from 'lucide-react'
import { ApiError } from '../api/client'
import {
  clearPendingDetailCache,
  fetchPendingDesignerDetail,
  filterToPeriod,
  loadDesignerQr,
  payDesigner,
  periodToFilter,
  type PaymentPeriod,
  type PendingDesignerDetail,
  type PeriodFilterValue,
} from '../features/payments/api'
import { PaymentPeriodFilter } from './PaymentPeriodFilter'
import { useToast } from '../context/ToastContext'

const money = (n: number) => `${n.toLocaleString('vi-VN')} đ`

/**
 * Pay one Designer: the amount for the chosen week / date range on the left (it follows the
 * filter), their bank QR on the right. The order list is not shown, but it is still loaded and
 * sent back as-is on payment, so a server-side change (a new order arriving, a rate edited) is
 * refused rather than silently charging a different amount. After paying, the period reads 0.
 */
export function DesignerPayModal({
  designerId,
  designerName,
  period = null,
  onClose,
  onPaid,
}: {
  designerId: string
  designerName: string
  /** The period chosen on the list; the popup starts with it and can change it. */
  period?: PaymentPeriod | null
  onClose: () => void
  onPaid: () => void
}) {
  const { showToast: toast } = useToast()
  const [filter, setFilter] = useState<PeriodFilterValue>(() => periodToFilter(period))
  const { period: activePeriod, invalid } = filterToPeriod(filter)
  const periodKey = JSON.stringify(activePeriod)
  const [detail, setDetail] = useState<PendingDesignerDetail | null>(null)
  const [empty, setEmpty] = useState(false) // nothing waiting in this period (never loaded, or already paid)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [qrUrls, setQrUrls] = useState<string[]>([])
  const [qrLoading, setQrLoading] = useState(false)
  const [paying, setPaying] = useState(false)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    if (invalid) return
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchPendingDesignerDetail(designerId, activePeriod)
      .then((d) => { if (!cancelled) { setDetail(d); setEmpty(false) } })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) {
          setDetail(null)
          setEmpty(true)
        } else {
          setError(err instanceof ApiError ? err.message : 'Không tải được số tiền.')
        }
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // periodKey stands for activePeriod
  }, [designerId, periodKey, invalid, reload])

  useEffect(() => {
    let cancelled = false
    setQrLoading(true)
    loadDesignerQr(designerId)
      .then((urls) => { if (!cancelled) setQrUrls(urls) })
      .catch(() => { if (!cancelled) setQrUrls([]) })
      .finally(() => { if (!cancelled) setQrLoading(false) })
    return () => { cancelled = true }
  }, [designerId])

  async function confirmPaid() {
    if (!detail) return
    if (!window.confirm('Bạn chắc chắn đã thanh toán xong rồi chứ?')) return
    setPaying(true)
    try {
      await payDesigner(designerId, detail.orders.map((o) => o.order_id), detail.pending_amount)
      toast(`Đã ghi nhận thanh toán ${detail.pending_count} đơn cho ${detail.designer_name}.`, 'success')
      clearPendingDetailCache()
      onPaid() // refresh the list behind
      setReload((n) => n + 1) // this period now reads 0
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast(err.message, 'error')
        onPaid() // the list changed under us: refresh it so the accountant reopens with current data
        onClose()
      } else {
        toast(err instanceof ApiError ? err.message : 'Không thanh toán được.', 'error')
      }
    } finally {
      setPaying(false)
    }
  }

  const name = detail?.designer_name || designerName
  const amount = detail?.pending_amount ?? 0
  const count = detail?.pending_count ?? 0

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/70 p-4" onClick={onClose}>
      <div
        data-testid="designer-pay-modal"
        className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-5 py-4">
          <h3 className="text-sm font-bold text-slate-900">{name || 'Thanh toán'}</h3>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-200 hover:text-slate-700" aria-label="Đóng">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="grid flex-1 overflow-y-auto md:grid-cols-2">
          <div className="flex flex-col gap-4 border-b border-slate-200 p-5 md:border-b-0 md:border-r">
            <PaymentPeriodFilter value={filter} onChange={setFilter} />
            {invalid && <p className="rounded-lg bg-red-50 px-3 py-1.5 text-xs text-red-700">Ngày bắt đầu phải trước ngày kết thúc.</p>}

            <div className="mt-2 text-center md:text-left">
              <p className="text-xs font-semibold text-slate-500">Số tiền cần thanh toán</p>
              {error ? (
                <p className="mt-2 text-sm text-rose-600">{error}</p>
              ) : loading ? (
                <div className="mt-3 flex items-center gap-2 text-sm text-slate-500">
                  <Loader2 className="h-5 w-5 animate-spin" />Đang tải...
                </div>
              ) : (
                <>
                  <p data-testid="pay-amount" className="mt-1 text-3xl font-extrabold text-slate-900">{money(invalid ? 0 : amount)}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {empty && !invalid ? 'Không có đơn chờ thanh toán trong khoảng này.' : `${invalid ? 0 : count} đơn`}
                  </p>
                </>
              )}
            </div>

            <button
              type="button"
              onClick={confirmPaid}
              disabled={paying || loading || !detail || invalid}
              className="mt-auto flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50"
            >
              {paying ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              Xác nhận đã thanh toán
            </button>
          </div>

          <div className="flex items-center justify-center p-5">
            {qrLoading ? (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Loader2 className="h-5 w-5 animate-spin" />Đang tải QR...
              </div>
            ) : qrUrls.length === 0 ? (
              <div className="flex flex-col items-center gap-2 text-center text-sm text-slate-500">
                <ImageIcon className="h-8 w-8 text-slate-300" />
                <p>Designer chưa tải ảnh QR ngân hàng.</p>
                <p className="text-xs text-slate-400">Vẫn có thể xác nhận đã thanh toán nếu bạn đã trả bằng cách khác.</p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3">
                {qrUrls.map((url, i) => (
                  <img key={i} src={url} alt={`QR ${i + 1} của ${name}`} className="max-h-[56vh] max-w-full rounded-lg object-contain shadow" />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
