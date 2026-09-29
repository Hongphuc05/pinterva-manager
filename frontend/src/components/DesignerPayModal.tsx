import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowLeft, CheckCircle2, Image as ImageIcon, Loader2, Package, QrCode, X } from 'lucide-react'
import { apiFetch, apiFetchBlob, ApiError } from '../api/client'
import { fetchPendingDesignerDetail, payDesigner, type PendingDesignerDetail } from '../features/payments/api'
import { useToast } from '../context/ToastContext'
import type { BankQrImage } from './BankQrManager'

const money = (n: number) => `${n.toLocaleString('vi-VN')} đ`
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString('vi-VN') : '—')

type Stage = 'list' | 'qr'

/**
 * Detail + pay flow for one Designer: their orders waiting for payment (count/total only, no
 * per-order rate), then the bank QR and "Xác nhận đã thanh toán". The order list and total are
 * frozen at load time and sent back as-is on payment, so a server-side change (a new order
 * arriving, a rate edited) is refused rather than silently charging a different amount.
 */
export function DesignerPayModal({
  designerId,
  onClose,
  onPaid,
}: {
  designerId: string
  onClose: () => void
  onPaid: () => void
}) {
  const { showToast: toast } = useToast()
  const [detail, setDetail] = useState<PendingDesignerDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [stage, setStage] = useState<Stage>('list')
  const [qrUrls, setQrUrls] = useState<string[]>([])
  const [qrLoading, setQrLoading] = useState(false)
  const [paying, setPaying] = useState(false)

  useEffect(() => {
    fetchPendingDesignerDetail(designerId)
      .then(setDetail)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Không tải được danh sách đơn.'))
  }, [designerId])

  useEffect(() => {
    if (stage !== 'qr') return
    let cancelled = false
    setQrLoading(true)
    apiFetch<{ images: BankQrImage[] }>(`/users/${designerId}/bank-qr`)
      .then((res) => Promise.all(res.images.map((img) => apiFetchBlob(img.url).then((blob) => URL.createObjectURL(blob)))))
      .then((urls) => { if (!cancelled) setQrUrls(urls) })
      .catch(() => { if (!cancelled) setQrUrls([]) })
      .finally(() => { if (!cancelled) setQrLoading(false) })
    return () => { cancelled = true }
  }, [stage, designerId])

  useEffect(() => () => qrUrls.forEach((u) => URL.revokeObjectURL(u)), [qrUrls])

  async function confirmPaid() {
    if (!detail) return
    if (!window.confirm('Bạn chắc chắn đã thanh toán xong rồi chứ?')) return
    setPaying(true)
    try {
      await payDesigner(designerId, detail.orders.map((o) => o.order_id), detail.pending_amount)
      toast(`Đã ghi nhận thanh toán ${detail.pending_count} đơn cho ${detail.designer_name}.`, 'success')
      onPaid()
      onClose()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast(err.message, 'error')
        onPaid() // the list changed under us: refresh it so the accountant reopens with current data
        onClose()
      } else {
        toast(err instanceof ApiError ? err.message : 'Không thanh toán được.', 'error')
        setPaying(false)
      }
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/70 p-4" onClick={onClose}>
      <div
        data-testid="designer-pay-modal"
        className="flex max-h-[88vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-5 py-4">
          <div className="flex items-center gap-2">
            {stage === 'qr' && (
              <button type="button" onClick={() => setStage('list')} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700" aria-label="Quay lại">
                <ArrowLeft className="h-4 w-4" />
              </button>
            )}
            <div>
              <h3 className="text-sm font-bold text-slate-900">{detail?.designer_name || 'Đang tải...'}</h3>
              <p className="text-xs text-slate-500">{stage === 'qr' ? 'Quét QR để chuyển khoản' : 'Đơn chờ thanh toán'}</p>
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-200 hover:text-slate-700" aria-label="Đóng">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {error ? (
            <p className="px-5 py-10 text-center text-sm text-rose-600">{error}</p>
          ) : !detail ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500">
              <Loader2 className="h-5 w-5 animate-spin" />Đang tải...
            </div>
          ) : stage === 'list' ? (
            <ul className="divide-y divide-slate-100">
              {detail.orders.map((o) => (
                <li key={o.order_id} className="flex items-center gap-3 px-5 py-3">
                  <div className="grid h-10 w-10 flex-none place-items-center overflow-hidden rounded-lg bg-slate-100">
                    {o.thumbnail_url ? <img src={o.thumbnail_url} alt="" className="h-full w-full object-cover" /> : <Package className="h-4 w-4 text-slate-400" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-xs font-bold text-slate-800">{o.external_order_id}</p>
                    <p className="truncate text-xs text-slate-500">{o.product_name || '—'}</p>
                  </div>
                  <span className="flex-none text-xs text-slate-400">{when(o.submitted_at)}</span>
                </li>
              ))}
            </ul>
          ) : qrLoading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500">
              <Loader2 className="h-5 w-5 animate-spin" />Đang tải QR...
            </div>
          ) : qrUrls.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-16 text-center text-sm text-slate-500">
              <ImageIcon className="h-8 w-8 text-slate-300" />
              <p>Designer chưa tải ảnh QR ngân hàng.</p>
              <p className="text-xs text-slate-400">Vẫn có thể xác nhận đã thanh toán nếu bạn đã trả bằng cách khác.</p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3 py-6">
              {qrUrls.map((url, i) => (
                <img key={i} src={url} alt={`QR ${i + 1} của ${detail.designer_name}`} className="max-h-[46vh] max-w-[85%] rounded-lg object-contain shadow" />
              ))}
            </div>
          )}
        </div>

        {detail && (
          <div className="border-t border-slate-200 bg-slate-50 px-5 py-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-500">{detail.pending_count} đơn</span>
              <span className="text-base font-bold text-slate-900">{money(detail.pending_amount)}</span>
            </div>
            {stage === 'list' ? (
              <button
                type="button"
                onClick={() => setStage('qr')}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#0052CC] px-4 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-[#0041A3]"
              >
                <QrCode className="h-4 w-4" />Thanh toán
              </button>
            ) : (
              <button
                type="button"
                onClick={confirmPaid}
                disabled={paying}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50"
              >
                {paying ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                Xác nhận đã thanh toán
              </button>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
