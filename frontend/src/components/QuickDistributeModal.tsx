import { useState, useMemo } from 'react'
import {
  X,
  Zap,
  Users,
  AlertTriangle,
  RotateCcw,
  Equal,
  Loader2,
  CheckCircle2,
} from 'lucide-react'
import { apiFetch, ApiError } from '../api/client'
import type { OrderSummary, UserOption } from '../pages/OrdersListPage'

const DEFAULT_PLATFORM_DES = 'nguyễn thị thúy hường 2d'

export type QuickDistributeModalProps = {
  isOpen: boolean
  onClose: () => void
  waitingOrders: OrderSummary[]
  designers: UserOption[]
  onSuccess: () => Promise<void>
  setFlash: (msg: string) => void
}

export function QuickDistributeModal({
  isOpen,
  onClose,
  waitingOrders,
  designers,
  onSuccess,
  setFlash,
}: QuickDistributeModalProps) {
  const [allocations, setAllocations] = useState<Record<string, number>>({})
  const [submitting, setSubmitting] = useState(false)
  const [showWarning, setShowWarning] = useState(false)
  const [warningUncheckCount, setWarningUncheckCount] = useState(0)

  const totalWaiting = waitingOrders.length

  const totalAllocated = useMemo(() => {
    return Object.values(allocations).reduce((sum, val) => sum + (Number.isFinite(val) && val > 0 ? val : 0), 0)
  }, [allocations])

  const remaining = totalWaiting - totalAllocated

  if (!isOpen) return null

  function handleCountChange(designerId: string, valStr: string) {
    const parsed = parseInt(valStr, 10)
    const count = isNaN(parsed) || parsed < 0 ? 0 : parsed
    setAllocations((prev) => ({
      ...prev,
      [designerId]: count,
    }))
  }

  function handleDistributeEvenly() {
    if (designers.length === 0 || totalWaiting === 0) return
    const baseCount = Math.floor(totalWaiting / designers.length)
    const remainder = totalWaiting % designers.length

    const nextAllocations: Record<string, number> = {}
    designers.forEach((des, idx) => {
      nextAllocations[des.id] = baseCount + (idx < remainder ? 1 : 0)
    })
    setAllocations(nextAllocations)
  }

  function handleClearAll() {
    setAllocations({})
  }

  function handleConfirmClick() {
    if (totalAllocated <= 0 || totalAllocated > totalWaiting) return

    // Collect orders that will be distributed
    const ordersToDistribute = waitingOrders.slice(0, totalAllocated)
    const uncheckOrders = ordersToDistribute.filter(
      (o) => !o.duplicate_check_status || o.duplicate_check_status === 'uncheck'
    )

    if (uncheckOrders.length > 0) {
      setWarningUncheckCount(uncheckOrders.length)
      setShowWarning(true)
    } else {
      executeDistribution()
    }
  }

  async function executeDistribution() {
    setSubmitting(true)
    setShowWarning(false)

    try {
      let offset = 0
      let totalQueued = 0

      for (const des of designers) {
        const count = allocations[des.id] || 0
        if (count > 0) {
          const slice = waitingOrders.slice(offset, offset + count)
          offset += count
          const orderIds = slice.map((o) => o.id)
          const platformDes = des.platform_designer_option || DEFAULT_PLATFORM_DES

          const res = await apiFetch<{ queued_count: number }>('/assignments', {
            method: 'POST',
            body: JSON.stringify({
              order_ids: orderIds,
              designer_id: des.id,
              printerval_designer: platformDes,
              printerval_status: 'Doing',
            }),
          })
          totalQueued += res.queued_count || orderIds.length
        }
      }

      setFlash(`Đã phân công nhanh ${totalQueued} đơn cho các Designer sang Doing và cập nhật Print.`)
      onClose()
      await onSuccess()
    } catch (err) {
      if (err instanceof ApiError) {
        alert(`Lỗi chia đơn nhanh: ${err.message}`)
      } else {
        alert('Đã xảy ra lỗi khi phân công nhanh.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-xs animate-in fade-in duration-150">
      <div className="relative w-full max-w-xl rounded-2xl bg-white shadow-2xl border border-slate-100 flex flex-col max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4 bg-gradient-to-r from-blue-50/50 via-white to-white">
          <div className="flex items-center gap-2.5">
            <div className="rounded-xl bg-[#0052CC]/10 p-2 text-[#0052CC]">
              <Zap className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-800">Chia Đơn Nhanh Cho Designer</h2>
              <p className="text-xs text-slate-500">Phân bổ tự động các đơn từ trên xuống dưới theo số lượng</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors disabled:opacity-50"
            title="Đóng"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Real-time Counter Stats */}
        <div className="grid grid-cols-3 gap-3 p-4 bg-slate-50/70 border-b border-slate-100">
          <div className="rounded-xl bg-white p-3 border border-slate-200/80 shadow-2xs">
            <span className="text-[11px] font-semibold text-slate-500 block uppercase tracking-wider">Tổng Đơn Chờ</span>
            <span className="text-lg font-mono font-extrabold text-slate-800">{totalWaiting}</span>
            <span className="text-xs text-slate-400 ml-1">đơn</span>
          </div>

          <div className="rounded-xl bg-white p-3 border border-slate-200/80 shadow-2xs">
            <span className="text-[11px] font-semibold text-slate-500 block uppercase tracking-wider">Đã Phân Bổ</span>
            <span className="text-lg font-mono font-extrabold text-[#0052CC]">{totalAllocated}</span>
            <span className="text-xs text-slate-400 ml-1">đơn</span>
          </div>

          <div
            className={`rounded-xl p-3 border shadow-2xs transition-colors ${
              remaining < 0
                ? 'bg-red-50 border-red-200 text-red-700'
                : remaining === 0
                ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                : 'bg-amber-50 border-amber-200 text-amber-800'
            }`}
          >
            <span className="text-[11px] font-semibold block uppercase tracking-wider opacity-80">Còn Lại</span>
            <span className="text-lg font-mono font-extrabold">{remaining}</span>
            <span className="text-xs opacity-75 ml-1">đơn</span>
          </div>
        </div>

        {/* Quick Toolbar */}
        <div className="flex items-center justify-between px-6 py-2.5 bg-white border-b border-slate-100">
          <span className="text-xs font-semibold text-slate-600 flex items-center gap-1.5">
            <Users className="h-3.5 w-3.5 text-slate-400" />
            Danh sách Designer ({designers.length})
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleDistributeEvenly}
              disabled={submitting || designers.length === 0 || totalWaiting === 0}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold text-[#0052CC] hover:bg-blue-50 rounded-lg border border-blue-200 transition-colors disabled:opacity-50"
              title="Chia đều tổng số đơn cho các Designer"
            >
              <Equal className="h-3 w-3" />
              <span>Chia đều</span>
            </button>
            <button
              type="button"
              onClick={handleClearAll}
              disabled={submitting || totalAllocated === 0}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg border border-slate-200 transition-colors disabled:opacity-50"
              title="Xóa tất cả số lượng đã nhập"
            >
              <RotateCcw className="h-3 w-3" />
              <span>Xóa hết</span>
            </button>
          </div>
        </div>

        {/* Table Body */}
        <div className="flex-1 overflow-y-auto px-6 py-3 max-h-[340px]">
          {designers.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-400">Không có Designer nào trong hệ thống.</div>
          ) : (
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-100 text-[11px] font-bold text-slate-500 uppercase">
                  <th className="pb-2">Designer</th>
                  <th className="pb-2 w-32 text-right">Số đơn phân bổ</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {designers.map((des) => {
                  const val = allocations[des.id] || 0
                  return (
                    <tr key={des.id} className="hover:bg-slate-50/60 transition-colors">
                      <td className="py-2.5 pr-3">
                        <div className="font-bold text-slate-800 text-xs">{des.full_name || des.username}</div>
                        <div className="text-[11px] text-slate-400 flex items-center gap-1.5">
                          <span>@{des.username}</span>
                          {des.platform_designer_option && (
                            <span className="text-slate-400">• Web mẹ: {des.platform_designer_option}</span>
                          )}
                        </div>
                      </td>
                      <td className="py-2.5 pl-3 text-right">
                        <div className="inline-flex items-center gap-1.5 justify-end">
                          <input
                            type="number"
                            min="0"
                            max={totalWaiting}
                            value={val === 0 ? '' : val}
                            placeholder="0"
                            disabled={submitting}
                            onChange={(e) => handleCountChange(des.id, e.target.value)}
                            className="w-24 px-3 py-1.5 text-right font-mono font-bold text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] disabled:bg-slate-100"
                          />
                          <span className="text-slate-400 text-xs w-6 text-left">đơn</span>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50/50 px-6 py-3.5">
          <div className="text-xs text-slate-500">
            {remaining < 0 ? (
              <span className="text-red-600 font-semibold">⚠️ Tổng số đơn vượt quá số lượng chờ ({Math.abs(remaining)} đơn)</span>
            ) : totalAllocated > 0 ? (
              <span className="text-slate-600">Sẽ chia <strong>{totalAllocated}</strong> đơn đầu tiên từ trên xuống</span>
            ) : (
              <span>Nhập số lượng đơn cho từng Designer</span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-2 text-xs font-bold text-slate-600 bg-white hover:bg-slate-100 border border-slate-200 rounded-xl transition-colors disabled:opacity-50"
            >
              Hủy
            </button>
            <button
              type="button"
              onClick={handleConfirmClick}
              disabled={submitting || totalAllocated === 0 || remaining < 0}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl shadow-xs transition-colors disabled:opacity-50"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>Đang chia đơn...</span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  <span>Xác nhận chia ({totalAllocated} đơn)</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Warning Modal for Uncheck Orders */}
        {showWarning && (
          <div className="absolute inset-0 z-60 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-xs animate-in fade-in duration-100">
            <div className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-2xl border border-amber-200 space-y-4">
              <div className="flex items-start gap-3">
                <div className="rounded-full bg-amber-100 p-2 text-amber-600 shrink-0">
                  <AlertTriangle className="h-6 w-6" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-800">Cảnh báo đơn chưa check trùng</h3>
                  <p className="mt-1 text-xs text-slate-600 leading-relaxed">
                    Có <strong className="text-amber-700 font-bold">{warningUncheckCount} đơn</strong> trong số các đơn sắp chia chưa được kiểm tra trùng lặp.
                  </p>
                  <p className="mt-1 text-xs text-slate-500">Bạn có chắc chắn muốn tiếp tục chia các đơn này cho Designer không?</p>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowWarning(false)}
                  disabled={submitting}
                  className="px-3.5 py-1.5 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors disabled:opacity-50"
                >
                  Quay lại kiểm tra
                </button>
                <button
                  type="button"
                  onClick={executeDistribution}
                  disabled={submitting}
                  className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-bold text-white bg-amber-600 hover:bg-amber-700 rounded-xl transition-colors disabled:opacity-50"
                >
                  {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>Vẫn tiếp tục chia</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
